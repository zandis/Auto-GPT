# D-315 The site's time zone is one setting: site.tz, carried by TB_TZ, with no code default

**D-315 The site's time zone is one setting. `site.tz` in settings.yaml is the source, `TB_TZ` carries it to the
containers, and no code carries a zone of its own: a process with neither stops with a message instead of reading
Taiwan's day in Japan. `trialbox doctor` fails when site.tz, TB_TZ, the data source mapping's `tz` and the host's zone
differ, and the host log day is the site's day.**
Task T-656 (wave 2 of TB-PLAN-06). Branch `agent/T-656-site-tz`, after PR #86 (D-270). Date 2026-11-10.
Status: proposed (in review). Findings: STD-016, OPS-036, OPS-056.

## Decision

* **One accessor.** `tb_common.config.site_tz(tz=None)` returns the zone a caller has (`cfg.env.tz`, a mapping's
  `tz`), else `TB_TZ`, else raises `ConfigError`. `site_zone()` is the same as a `ZoneInfo`. `Env.tz` has no default:
  `load_env` leaves it empty when `TB_TZ` is unset, and `load()` fills it from `site.tz` as before. `Env.zone` raises
  when it is still empty. `load_settings` refuses an empty `site.tz`.
* **No default in code.** The defaults `"Asia/Taipei"` of `timeutil.now/today`, the lake (`Lake`, `LakeLocal`,
  `Flattener`, the lake app), the OMOP loader and its CLI, the data platform's CSV path, the compiler's deps, the
  outbound mail, the gateway's audit zone (it read `TZ_SITE`, a name nothing sets), the REDCap simulator and the
  console CLI audit now come from `site_tz()`. A mapping without `tz` is refused (`MappingError`).
* **Fixed synthetic instants are not zones.** The recall simulation's `T0` and the cascade certificate's audit start
  are fixed instants; they keep their value and their `+08:00` text as a fixed offset.
* **Deploy.** Compose starts HAPI with `-Duser.timezone=${TB_TZ:?...}`: a box without TB_TZ does not start. The
  platform manifest takes `TB_TZ` from the `trialbox-env` ConfigMap (`site.env`). The settings wizard asks the zone
  with no default and refuses one that differs from the mapping's `tz`.
* **Doctor check `site_tz`.** FAIL when neither site.tz nor TB_TZ is set, when a name is not a zone, or when any two
  of site.tz, TB_TZ, the mapping's tz and the host's zone differ (two names that agree on the offset every day for a
  year, such as `Japan` and `Asia/Tokyo`, are the same zone). The host zone comes from `TB_HOST_TZ` (check_host.sh
  passes it when doctor runs in the box image), else /etc/timezone or the /etc/localtime link; inside a container
  without `TB_HOST_TZ` it is not compared and the detail says so.
* **Log day.** `trialbox logs collect` takes the site's day (00:00 to 24:00 in `TB_TZ`, the zone of the audit day
  files), not the UTC day, and refuses to run without `TB_TZ`.
* **Lint.** `tests/unit/test_site_tz.py` fails on an `Asia/Taipei` string in code outside settings and tests. Its
  allowlist names each exception: `derived.country_of` (recognises Taiwan's zone), the test harnesses that build the
  synthetic Taiwan demo site, and three fix-group files left for their groups.

## Not done here

* `libs/tb_common/audit.py` (`AuditLog` default), `services/adapter/pipeline.py` (`AdapterConfig` default) and
  `tools/trialbox/backup_schedule.py` (fallback zone) belong to open fix groups. Their defaults go when the groups
  close; the allowlist entry then fails as stale and is removed.
* The host cron files (`deploy/backup/*.cron`) still run in host local time; doctor now fails when the host zone is
  not the site's, which is what OPS-056 asked.
