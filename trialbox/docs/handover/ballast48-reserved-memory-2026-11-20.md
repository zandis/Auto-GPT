# The ballast and ballast48 read free memory differently (card H-66, 2026-11-20)

**Reader:** the people who build TrialBox

Lane H. Finding H66-01 ([findings JSON](ballast48-reserved-memory-2026-11-20.json)).

## What the run's logs show

The 48 GB run m48-20261119T232459Z-d28f6c0305fa passed s01 to s06 and ended at s07 with nothing measured.

- `records/ballast.log`: the card has 97,887 MiB in all; target 49,140 MiB free. The holder said "holding 47551 MiB
  ... 49140 MiB free left", then "ready".
- `logs/s07-ballast.log`: "ballast48: refused: 49776 MiB free, not 49140 +/- 512".

## The cause

Driver 580 reserves memory that nvidia-smi counts neither used nor free: total = used + free + reserved. The two
tools read "free" differently:

- `tools/ballast.py` `hold` read `memory.free` from nvidia-smi (`read_card`) and checked it: 49,140.
- `tools/ballast48.py` `read_card` asked only for `memory.total,memory.used` and set free = total - used. That
  adds the reserve: 49,140 + 636 = 49,776. So it refused.

The arithmetic: 97,887 - 47,551 = 50,336 = 49,140 free + 636 reserved + 560 (the holder's own CUDA context, which
nvidia-smi counts as used). And 49,776 - 49,140 = 636 is the reserve at s07's read. The integrator's figure of
637 MiB is one more than that. Per-field rounding in nvidia-smi or a 1 MiB move between the two reads could explain
it. Either way, the 636 is the reserve. The holder did not give memory back.

## The fix

- One definition of free: nvidia-smi's `memory.free`, what a new process (a model server) is offered. One function
  reads it: `tools/ballast.py` `read_card`. `tools/ballast48.py` now reads the card through it (`Card.reserved` =
  total - used - free).
- `hold` does not rely on one subtraction. After the holder's first estimate it reads free. It then asks the holder
  for more or less over the holder's stdin, in steps of the measured difference. It stops within 64 MiB of the
  target, or after 8 steps. Still outside 512 MiB: refused `off-target` with the figures, exit 2.
- Holding steady: the holder keeps every tensor referenced and never frees them by itself. Its allocator cache is
  emptied only when `hold` asks for less. `hold` waits 2 s and reads free again before "ready". If it moved out of
  512 MiB, it refuses `unsteady`. ballast48's own check at s07 still refuses a card that is off.
- ballast48's view and `during` count memory from the target's free, with the reserve included. A server that
  takes 30,000 MiB shows as 30,000 used on the 49,140 MiB card. Without the change it would show 29,364.
- `tools/measure48-vm.sh`: a `ballast48 plan` refusal's own line is now the s07 note. So the run's end reason names
  both figures. Before, it said only "ballast48 plan refused (records/plan.txt)".
- Not changed: the 512 MiB tolerance, every refusal, the "by ballast" capping (never a tier record), and the cap,
  the stop line and the cost figures in the driver.

## The stand-in

`tests/unit/test_ballast_reserved_h66.py` models the card from the run's figures: 97,887 MiB, 636 reserved, 560 MiB
holder context. On master's code it gives the run's failure exactly: the holder says "49140 MiB free left" and
"ready", then the s07 check refuses "49776 MiB free, not 49140 +/- 512". With the fix the check reads 49,140.

Further cases:
- no reserve: the old figures hold;
- another process already holds memory: refused unless expected; when expected, the holder takes that much less;
- the holder's first estimate off by -700, +700 or +2,000 MiB: corrected;
- a holder that moves by halves: converges in 5 steps;
- a holder that cannot be corrected: refused with the numbers, exit 2;
- memory given back before "ready": refused `unsteady`;
- memory given back after "ready": still refused at s07;
- a CLI run with a fake nvidia-smi and docker: one correction over the pipe, then `ballast48 plan` agrees.

The VM script's rehearsal (`tests/unit/test_measure48_vm_h53.py`) has a new case. A plan refusal ends the run
cleanly: the ballast is released, the records go up, the VM powers off, and the end reason names both figures.

## Not verified

No card was used. Not run here:
- the real holder in the vLLM image, including torch's `empty_cache` on a shrink;
- nvidia-smi's `memory.free` under driver 580;
- whether it equals the free figure vLLM reads at start-up (`cudaMemGetInfo`).

The next run's `ballast.log` shows each correction and the reserve, so the launch itself checks these.

`tools/dgpu48.py` (lane J, read only) reads only `memory.used` on the card. It does not compute free as total
minus used, so it does not share the fault.
