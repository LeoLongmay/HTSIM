// -*- c-basic-offset: 4; indent-tabs-mode: nil -*-
#ifndef MOTIVATION_EPOCH_H
#define MOTIVATION_EPOCH_H

#include <algorithm>
#include <cstdint>
#include <optional>
#include <set>

#include "prism_decompose.h"

struct MotivationEpochResult {
    uint64_t epoch_id;
    uint64_t start_ps;
    uint64_t end_ps;
    uint32_t sample_count;
    uint64_t raw_floor_ps;
    uint64_t raw_spread_ps;
    uint64_t smooth_floor_ps;
    uint64_t smooth_spread_ps;
    prism::Region observed_region;
    uint32_t entropy_coverage;
    uint32_t physical_path_coverage;
};

class MotivationEpochObserver {
public:
    static constexpr uint64_t NO_PHYSICAL_PATH = UINT64_MAX;

    MotivationEpochObserver(double kappa, uint32_t n_min, double smooth_beta,
                            double hysteresis)
        : _kappa(kappa),
          _n_min(n_min),
          _smooth_beta(smooth_beta),
          _hysteresis(hysteresis) {}

    std::optional<MotivationEpochResult> observe(
        uint64_t now_ps, uint64_t qdelay_ps, bool genuine, uint32_t entropy,
        uint64_t physical_path_id, uint64_t base_rtt_ps, uint64_t target_cc_ps = 0,
        uint64_t target_spray_ps = 0) {
        if (!genuine) {
            return std::nullopt;
        }

        if (_samples == 0) {
            _start_ps = now_ps;
            _min_ps = qdelay_ps;
            _max_ps = qdelay_ps;
        } else {
            _min_ps = std::min(_min_ps, qdelay_ps);
            _max_ps = std::max(_max_ps, qdelay_ps);
        }
        ++_samples;
        _entropies.insert(entropy);
        if (physical_path_id != NO_PHYSICAL_PATH) {
            _physical_paths.insert(physical_path_id);
        }

        const uint64_t duration_ps = now_ps - _start_ps;
        const uint64_t required_duration_ps =
            static_cast<uint64_t>(_kappa * static_cast<double>(base_rtt_ps));
        if (duration_ps < required_duration_ps || _samples < _n_min) {
            return std::nullopt;
        }

        const uint64_t raw_floor_ps = _min_ps;
        const uint64_t raw_spread_ps = _max_ps - _min_ps;
        if (!_smooth_initialized) {
            _smooth_floor_ps = raw_floor_ps;
            _smooth_spread_ps = raw_spread_ps;
            _smooth_initialized = true;
        } else {
            _smooth_floor_ps = static_cast<uint64_t>(
                _smooth_beta * raw_floor_ps + (1.0 - _smooth_beta) * _smooth_floor_ps);
            _smooth_spread_ps = static_cast<uint64_t>(
                _smooth_beta * raw_spread_ps + (1.0 - _smooth_beta) * _smooth_spread_ps);
        }

        const uint64_t effective_target_spray_ps =
            target_spray_ps > 0 ? target_spray_ps : target_cc_ps;
        const prism::Region observed_region = _hysteresis > 0.0
            ? prism::decide_region_hyst(_smooth_floor_ps, _smooth_spread_ps, target_cc_ps,
                                        effective_target_spray_ps, _hysteresis, _region)
            : prism::decide_region(_smooth_floor_ps, _smooth_spread_ps, target_cc_ps,
                                   effective_target_spray_ps);
        _region = observed_region;

        MotivationEpochResult result{
            _epoch_id,
            _start_ps,
            now_ps,
            _samples,
            raw_floor_ps,
            raw_spread_ps,
            _smooth_floor_ps,
            _smooth_spread_ps,
            observed_region,
            static_cast<uint32_t>(_entropies.size()),
            static_cast<uint32_t>(_physical_paths.size())};

        ++_epoch_id;
        _samples = 0;
        _entropies.clear();
        _physical_paths.clear();
        return result;
    }

    uint64_t currentEpochId() const { return _epoch_id; }
    uint32_t currentSampleCount() const { return _samples; }

private:
    double _kappa;
    uint32_t _n_min;
    double _smooth_beta;
    double _hysteresis;

    uint64_t _epoch_id = 0;
    uint64_t _start_ps = 0;
    uint64_t _min_ps = 0;
    uint64_t _max_ps = 0;
    uint32_t _samples = 0;
    uint64_t _smooth_floor_ps = 0;
    uint64_t _smooth_spread_ps = 0;
    bool _smooth_initialized = false;
    prism::Region _region = prism::INCREASE;
    std::set<uint32_t> _entropies;
    std::set<uint64_t> _physical_paths;
};

#endif  // MOTIVATION_EPOCH_H
