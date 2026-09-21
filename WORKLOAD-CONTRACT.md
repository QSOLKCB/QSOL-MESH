# QSOL-MESH Workload Contract

Every workload adapter must declare a versioned machine-readable contract containing workload identity/version, logical domain, admissible partitions, partial-result format, reduction semantics, canonical/reference or independent oracle, exactness/tolerance, memory requirements/forbidden caching, side-effect boundary, and claim boundary.

MESH may partition only at workload-admitted boundaries and may not guess semantic equivalence between implementations.

GALAXY is the first planned external adapter because disjoint logical-ID ranges can be regenerated locally and compactly reduced. PR #1 copies no GALAXY source into MESH.
