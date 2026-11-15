# D-889 qualify in the image reports the host's NVIDIA driver

- **Task:** HOST-GPU, the integrator's follow-up to D-881 from lane G's probe (#639, 2026-11-15)
- **PR:** this branch (`agent/HOST-GPU-qualify-reads-the-hosts-driver`)
- **Date:** 2026-11-15
- **Status:** accepted

## Decision

The serving record's driver, CUDA version and card are the host's: the trialbox-py container has no GPU and no
nvidia-smi. `qualify --box` reads them on the host (`box_qualify.host_gpu_versions`, nvidia-smi) and passes
`TB_HOST_GPU` (JSON); `qualify.gpu_versions` in the image uses it and records `driver_source`. No value, or a malformed
one, is still "no NVIDIA driver". A direct `docker run` of qualify sets TB_HOST_GPU the same way.

## Test

`tests/unit/test_qualify_host_gpu.py`: before, the two host cases failed; after, 9 passed.
