# Capacity-Controlled Workload Amendment Task 1

## Implementation

- Replaced M3's unused application offered-load metadata with source-NIC ceiling
  and healthy-ingress capacity facts.
- Recoverable uses six distinct 100 Gbps source NICs (600.0 Gbps) against
  800.0 Gbps healthy capacity and validates the strict less-than relation.
- Persistent uses twelve distinct 100 Gbps source NICs (1200.0 Gbps) against
  800.0 Gbps healthy capacity and validates the strict greater-than relation.
- Added a focused workload test covering both scenarios and distinct sources
  for seeds 13, 14, and 15.

## TDD Evidence

Red:

```text
ImportError: cannot import name 'scenario_capacity' from
'htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.run'
```

Green:

```text
python3 -m unittest htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.tests.test_workload -v
Ran 3 tests in 0.003s
OK

python3 -m unittest htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.tests.test_analyze -v
Ran 43 tests in 0.242s
OK
```

No simulations were run.

## High Review Finding Repair

Red:

```text
python3 -m unittest htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.tests.test_workload
ImportError: cannot import name 'add_workload_capacity' from 'htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.run'
Ran 1 test in 0.000s
FAILED (errors=1)
```

Green:

```text
python3 -m unittest htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.tests.test_workload
Ran 4 tests in 0.003s
OK

python3 -m unittest htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.tests.test_analyze
Ran 43 tests in 0.192s
OK
```

No simulations were run.
