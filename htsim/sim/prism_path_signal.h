#ifndef PRISM_PATH_SIGNAL_H
#define PRISM_PATH_SIGNAL_H

#include <algorithm>
#include <array>
#include <cstdint>
#include <map>
#include <vector>

namespace prism {

class P2Median {
public:
    void reset() {
        _count = 0;
        _initial.clear();
    }

    void observe(uint64_t value) {
        if (_count < 5) {
            _initial.push_back(value);
            ++_count;
            if (_count == 5) {
                std::sort(_initial.begin(), _initial.end());
                for (uint32_t i = 0; i < 5; ++i) {
                    _q[i] = _initial[i];
                    _n[i] = static_cast<double>(i + 1);
                    _np[i] = static_cast<double>(i + 1);
                }
            }
            return;
        }

        uint32_t k = 0;
        if (value < _q[0]) {
            _q[0] = value;
        } else if (value >= _q[4]) {
            _q[4] = value;
            k = 3;
        } else {
            while (k < 3 && value >= _q[k + 1])
                ++k;
        }
        for (uint32_t i = k + 1; i < 5; ++i)
            _n[i] += 1.0;
        for (uint32_t i = 0; i < 5; ++i)
            _np[i] += kDesiredIncrements[i];

        for (uint32_t i = 1; i < 4; ++i) {
            const double delta = _np[i] - _n[i];
            const double direction = delta >= 1.0 ? 1.0 : (delta <= -1.0 ? -1.0 : 0.0);
            if (direction == 0.0 ||
                (direction > 0.0 && _n[i + 1] - _n[i] <= 1.0) ||
                (direction < 0.0 && _n[i - 1] - _n[i] >= -1.0))
                continue;

            const double candidate = _q[i] + direction / (_n[i + 1] - _n[i - 1]) *
                ((_n[i] - _n[i - 1] + direction) * (_q[i + 1] - _q[i]) / (_n[i + 1] - _n[i]) +
                 (_n[i + 1] - _n[i] - direction) * (_q[i] - _q[i - 1]) / (_n[i] - _n[i - 1]));
            if (candidate > _q[i - 1] && candidate < _q[i + 1]) {
                _q[i] = candidate;
            } else {
                const uint32_t neighbor = direction > 0.0 ? i + 1 : i - 1;
                _q[i] += direction * (_q[neighbor] - _q[i]) / (_n[neighbor] - _n[i]);
            }
            _n[i] += direction;
        }
        ++_count;
    }

    bool empty() const { return _count == 0; }
    uint64_t count() const { return _count; }

    uint64_t median() const {
        if (_count == 0)
            return 0;
        if (_count < 5) {
            std::vector<uint64_t> values = _initial;
            std::sort(values.begin(), values.end());
            const uint32_t upper = static_cast<uint32_t>(values.size() / 2);
            const uint32_t lower = static_cast<uint32_t>((values.size() - 1) / 2);
            return values[lower] + (values[upper] - values[lower]) / 2;
        }
        return static_cast<uint64_t>(_q[2]);
    }

private:
    static constexpr std::array<double, 5> kDesiredIncrements{{0.0, 0.25, 0.5, 0.75, 1.0}};
    uint64_t _count = 0;
    std::vector<uint64_t> _initial;
    std::array<double, 5> _q{};
    std::array<double, 5> _n{};
    std::array<double, 5> _np{};
};

struct PathSignal {
    uint64_t floor = 0;
    uint64_t spread = 0;
    uint32_t observed_paths = 0;
};

class PathMedianEpoch {
public:
    void observe(uint32_t path_id, uint64_t delay) {
        _paths[path_id].observe(delay);
    }

    PathSignal signal(uint64_t min_samples_per_path = 1) const {
        PathSignal result;
        uint64_t ceiling = 0;
        for (const auto& entry : _paths) {
            if (entry.second.count() < min_samples_per_path)
                continue;
            const uint64_t delay = entry.second.median();
            if (result.observed_paths == 0 || delay < result.floor)
                result.floor = delay;
            if (result.observed_paths == 0 || delay > ceiling)
                ceiling = delay;
            ++result.observed_paths;
        }
        result.spread = result.observed_paths > 1 ? ceiling - result.floor : 0;
        return result;
    }

    void reset() { _paths.clear(); }

private:
    std::map<uint32_t, P2Median> _paths;
};

}  // namespace prism

#endif
