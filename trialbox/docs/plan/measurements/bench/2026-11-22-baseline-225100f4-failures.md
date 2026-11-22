# Baseline failures on the bench host, master 225100f4bf3e1a05d7c1435314467d2b2c385ba4

Full tier (unit, cross-card, guard, console, integration, property, e2e-simple, security), run with temp folders and test databases on a private memory mount, 46 min, 139 failing ids. Same steps as the gate cards' runs. A record for the integrator, not for merging until its method is checked.

## host gap, named

### tests/unit/test_ops_runner_on.py (4): the ops timer tests need the host's systemd user timers (named in the integrator's earlier lists)

- `test_doctor_fails_a_runner_that_never_ran[DEV-WARN]`: assert (1 == 0)
- `test_doctor_fails_a_runner_that_never_ran[PRODUCTION-FAIL]`: +  where 'the runner has never written <path> wait; trialbox-ops.timer is enabled: see systemctl status trialbox-ops.service and journalctl -u trialbox-ops.service' = Check(name='o
- `test_doctor_fails_a_runner_that_never_ran[TEST-WARN]`: +  where 'the runner has never written <path> wait; trialbox-ops.timer is enabled: see systemctl status trialbox-ops.service and journalctl -u trialbox-ops.service' = Check(name='o
- `test_doctor_fails_a_runner_that_never_ran[VALIDATION-FAIL]`: +  where 'the runner has never written <path> wait; trialbox-ops.timer is enabled: see systemctl status trialbox-ops.service and journalctl -u trialbox-ops.service' = Check(name='o

## not explained

### tests/unit/test_backup_key_ceremony.py (59)

- `test_a_backup_pub_that_appears_during_the_run_is_not_called_this_runs`: 
- `test_a_hostile_name_on_the_stick_is_refused_and_never_followed[dangling]`: 
- `test_a_hostile_name_on_the_stick_is_refused_and_never_followed[fifo]`: + refused: the public key's folder <path> is not there, or it or a folder above it is a link, another account's, or writable by others: nothing was written)
- `test_a_hostile_name_on_the_stick_is_refused_and_never_followed[folder]`: 
- `test_a_hostile_name_on_the_stick_is_refused_and_never_followed[hardlink]`: 
- `test_a_hostile_name_on_the_stick_is_refused_and_never_followed[huge]`: + refused: the public key's folder <path> is not there, or it or a folder above it is a link, another account's, or writable by others: nothing was written)
- `test_a_hostile_name_on_the_stick_is_refused_and_never_followed[symlink]`: 
- `test_a_journal_that_does_not_answer_in_time_stops_step_3`: assert 1 == 0
- `test_a_key_file_shown_to_others_after_step_1_says_the_key_is_exposed`: FileNotFoundError: [Errno 2] No such file or directory: '<path>
- `test_a_key_file_swapped_for_a_copy_before_the_read_back_is_refused`: + refused: the public key's folder <path> is not there, or it or a folder above it is a link, another account's, or writable by others: nothing was written)
- `test_a_key_file_that_reads_back_other_bytes_at_step_2_is_refused[same-key-other-bytes]`: 
- `test_a_key_file_that_reads_back_other_bytes_at_step_2_is_refused[torn]`: 
- `test_a_planted_whole_key_file_is_never_adopted`: ...Full output truncated, use '-vv' to show)
- `test_a_refusal_writes_nothing[a-no-op-orchestrator]`: + refused: the public key's folder <path> is not there, or it or a folder above it is a link, another account's, or writable by others: nothing was written)
- `test_a_refusal_writes_nothing[busy]`: + refused: the public key's folder <path> is not there, or it or a folder above it is a link, another account's, or writable by others: nothing was written)
- `test_a_refusal_writes_nothing[file-mode-journal]`: + refused: the public key's folder <path> is not there, or it or a folder above it is a link, another account's, or writable by others: nothing was written)
- `test_a_refusal_writes_nothing[journal-db-down]`: + refused: the public key's folder <path> is not there, or it or a folder above it is a link, another account's, or writable by others: nothing was written)
- `test_a_refusal_writes_nothing[journal-without-schema]`: + refused: the public key's folder <path> is not there, or it or a folder above it is a link, another account's, or writable by others: nothing was written)
- `test_a_refusal_writes_nothing[no-orchestrator]`: + refused: the public key's folder <path> is not there, or it or a folder above it is a link, another account's, or writable by others: nothing was written)
- `test_a_refusal_writes_nothing[no-stick]`: + refused: the public key's folder <path> is not there, or it or a folder above it is a link, another account's, or writable by others: nothing was written)
- `test_a_refusal_writes_nothing[no-tmpfile]`: + refused: the public key's folder <path> is not there, or it or a folder above it is a link, another account's, or writable by others: nothing was written)
- `test_a_refusal_writes_nothing[not-a-stick]`: + refused: the public key's folder <path> is not there, or it or a folder above it is a link, another account's, or writable by others: nothing was written)
- `test_a_refusal_writes_nothing[socket-not-roots]`: + refused: the public key's folder <path> is not there, or it or a folder above it is a link, another account's, or writable by others: nothing was written)
- `test_a_refusal_writes_nothing[stick-folder-shared]`: ...Full output truncated, use '-vv' to show)
- `test_a_rerun_with_another_empty_stick_abandons_the_first_and_says_so`: + refused: the public key's folder <path> is not there, or it or a folder above it is a link, another account's, or writable by others: nothing was written)
- `test_a_sheet_without_a_key_file_is_refused_before_a_key_is_made`: ...Full output truncated, use '-vv' to show)
- `test_a_stick_that_cannot_finish_a_run_is_refused_unchanged[other-site]`: 
- `test_a_stick_that_cannot_finish_a_run_is_refused_unchanged[sheet-line-swapped]`: 
- `test_a_stick_that_cannot_finish_a_run_is_refused_unchanged[sheet-of-another-key]`: 
- `test_a_stick_that_cannot_finish_a_run_is_refused_unchanged[torn-key]`: + refused: the public key's folder <path> is not there, or it or a folder above it is a link, another account's, or writable by others: nothing was written)
- `test_a_stick_that_shows_its_files_to_others_is_refused_then_finished_after_a_remount`: 
- `test_a_write_that_reads_back_wrong_on_its_own_descriptor_is_refused`: + refused: the public key's folder <path> is not there, or it or a folder above it is a link, another account's, or writable by others: nothing was written)
- `test_another_owner_of_a_stick_file_is_refused_before_any_key_exists`: ...Full output truncated, use '-vv' to show)
- `test_h1_not_dumpable_and_no_core_before_the_key_exists`: +  where 1 = CompletedProcess(args=['<path> '<path> is not there, or it or a folder above it is a link, another account's, or writable by others: nothing was written\n").returncode
- `test_h2_second_review_a_stick_folder_beside_the_backups_is_refused[elsewhere]`: 
- `test_h2_second_review_a_stick_folder_beside_the_backups_is_refused[equal]`: 
- `test_h2_second_review_a_stick_folder_beside_the_backups_is_refused[holds]`: 
- `test_h2_second_review_a_stick_folder_beside_the_backups_is_refused[inside]`: 
- `test_h2_second_review_a_stick_folder_beside_the_backups_is_refused[same-filesystem]`: 
- `test_h3_second_review_the_compose_project_is_this_checkouts_own`: +  where 1 = CompletedProcess(args=['bash', '<path> (the first-run page does not open again: the answers are applied). Then: sudo deploy/box-install.sh --firstrun\n").returncode
- `test_h_1_the_journal_is_asked_on_the_local_socket_whatever_docker_context_is_set`: 
- `test_h_3_a_rerun_syncs_the_files_a_run_cut_short_left`: + refused: the public key's folder <path> is not there, or it or a folder above it is a link, another account's, or writable by others: nothing was written)
- `test_h_4_a_write_cut_short_never_leaves_part_of_a_file_at_its_final_name`: 
- `test_h_5_no_key_is_made_while_swap_is_on_and_memory_cannot_be_locked`: assert 1 == 0
- `test_invariant_backup_pub_only_after_journal_and_read_back_across_every_stop_point[append_raises]`: 
- `test_invariant_backup_pub_only_after_journal_and_read_back_across_every_stop_point[fail_record]`: 
- `test_invariant_backup_pub_only_after_journal_and_read_back_across_every_stop_point[key-file]`: 
- `test_invariant_backup_pub_only_after_journal_and_read_back_across_every_stop_point[key-temp]`: 
- `test_invariant_backup_pub_only_after_journal_and_read_back_across_every_stop_point[pending]`: 
- `test_invariant_backup_pub_only_after_journal_and_read_back_across_every_stop_point[sheet-temp]`: 
- `test_invariant_backup_pub_only_after_journal_and_read_back_across_every_stop_point[silent]`: 
- `test_invariant_backup_pub_only_after_journal_and_read_back_across_every_stop_point[step1]`: 
- `test_invariant_backup_pub_only_after_journal_and_read_back_across_every_stop_point[step2]`: 
- `test_invariant_backup_pub_only_after_journal_and_read_back_across_every_stop_point[step3]`: 
- `test_invariant_backup_pub_only_after_journal_and_read_back_across_every_stop_point[step4-link]`: 
- `test_m6_a_public_folder_sync_that_fails_says_backup_pub_is_not_confirmed`: 
- `test_m6_a_stick_folder_sync_that_fails_with_einval_stops_before_the_journal`: 
- `test_the_ceremony_writes_the_stick_reads_it_back_records_and_then_makes_backup_pub`: 
- `test_the_paper_sheet_restores_by_its_printed_instruction`: assert 1 == 0

### tests/unit/test_install_refuses_unsafe_folders_10k4.py (44)

- `test_a_backup_target_counts_off_the_box_only_when_it_is_shown[/dev/shm-system`: 
- `test_a_backup_target_counts_off_the_box_only_when_it_is_shown[/mnt/data2/b-is`: 
- `test_a_backup_target_counts_off_the_box_only_when_it_is_shown[/mnt/disk2/no-such-is`: 
- `test_a_backup_target_counts_off_the_box_only_when_it_is_shown[/mnt/loop-its`: 
- `test_a_backup_target_counts_off_the_box_only_when_it_is_shown[/mnt/luks-its`: 
- `test_a_backup_target_counts_off_the_box_only_when_it_is_shown[/mnt/lvm/b-is`: 
- `test_a_backup_target_counts_off_the_box_only_when_it_is_shown[/mnt/nohw-its`: 
- `test_a_backup_target_counts_off_the_box_only_when_it_is_shown[/mnt/ram/b-is`: 
- `test_a_backup_target_counts_off_the_box_only_when_it_is_shown[/mnt/squash-is`: 
- `test_a_backup_target_counts_off_the_box_only_when_it_is_shown[/mnt/syspart/b-is`: 
- `test_a_backup_target_counts_off_the_box_only_when_it_is_shown[/mnt/zram-its`: 
- `test_a_backup_target_counts_off_the_box_only_when_it_is_shown[/proc-system`: 
- `test_a_backup_target_counts_off_the_box_only_when_it_is_shown[/srv/hid/disk-is`: 
- `test_a_backup_target_counts_off_the_box_only_when_it_is_shown[/srv/plain-is`: 
- `test_a_disk_holding_the_audit_folder_is_the_box_s`: Use -v to get more diff
- `test_a_host_python_without_yaml_gets_a_true_message`: assert ('bundle: verify' in '\x1b[1m==> host\x1b[0m\n    no GPU: structured criteria only (FEAS, NAV, COHORT); note criteria wait for a GPU or a p...K §5)\ninstall: nothing was loa
- `test_a_log_folder_that_breaks_the_rule_is_refused[/mnt/disk2/backup-a`: 
- `test_a_log_folder_that_breaks_the_rule_is_refused[/mnt/ram/b-tmpfs]`: assert (["the audit anchor folder /mnt/audit has a parent folder / that another account owns or may write: anybody who can wri...r where the second disk or the hospital's share is 
- `test_a_log_folder_that_breaks_the_rule_is_refused[/tmp/logs-system`: 
- `test_a_production_install_exits_before_finished_with_on_box_backups_or_an_unmountable_anchor[on_box_backups-box-install.sh]`: 
- `test_a_production_install_exits_before_finished_with_on_box_backups_or_an_unmountable_anchor[on_box_backups-install.sh`: 
- `test_a_production_install_exits_before_finished_with_on_box_backups_or_an_unmountable_anchor[on_box_backups-install.sh`: 
- `test_a_production_install_exits_before_finished_with_on_box_backups_or_an_unmountable_anchor[unmountable_anchor-box-install.sh]`: 
- `test_a_production_install_exits_before_finished_with_on_box_backups_or_an_unmountable_anchor[unmountable_anchor-install.sh`: 
- `test_a_production_install_exits_before_finished_with_on_box_backups_or_an_unmountable_anchor[unmountable_anchor-install.sh`: 
- `test_a_second_disk_not_named_in_tb_backup_offbox_is_refused`: assert (["the audit anchor folder /mnt/audit has a parent folder / that another account owns or may write: anybody who can wri...r where the second disk or the hospital's share is 
- `test_a_second_physical_disk_or_the_hospital_s_share_is_off_the_box[/mnt/disk2/backup]`: 
- `test_a_second_physical_disk_or_the_hospital_s_share_is_off_the_box[/mnt/nas/backup]`: 
- `test_a_share_is_not_counted_when_the_box_s_own_addresses_cannot_be_read`: 
- `test_a_stray_tb_install_signed_still_loads_the_bundle[another`: 
- `test_a_stray_tb_install_signed_still_loads_the_bundle[none]`: assert ('bundle: verify' in '\x1b[1m==> host\x1b[0m\n    no GPU: structured criteria only (FEAS, NAV, COHORT); note criteria wait for a GPU or a p...K §5)\ninstall: nothing was loa
- `test_a_system_disk_that_cannot_be_told_counts_no_local_disk`: assert 'cannot be told, so no local disk is counted' in "the audit anchor folder /mnt/audit has a parent folder / that another account owns or may write: anybody who can writ...bef
- `test_a_validation_box_is_judged_as_the_stricter_of_its_own_and_the_given[VALIDATION]`: 
- `test_a_validation_install_is_refused_only_for_its_anchor`: +  where 1 = CompletedProcess(args=['bash', '<path> (the first-run page does not open again: the answers are applied). Then: sudo deploy/box-install.sh --firstrun\n").returncode
- `test_an_anchor_under_a_folder_others_may_write_is_refused`: assert (["the audit anchor folder /mnt/self has a parent folder / that another account owns or may write: anybody who can writ...efore the console starts: set TB_AUDIT_ANCHOR_TARGE
- `test_box_install_asks_the_console_image_to_read_the_anchor_then_mounts_it`: 
- `test_box_install_finishes_once_the_share_is_mounted`: +  where 1 = CompletedProcess(args=['bash', '<path> (the first-run page does not open again: the answers are applied). Then: sudo deploy/box-install.sh --firstrun\n").returncode
- `test_box_install_stops_when_the_console_image_cannot_read_the_anchor`: +  and   'finish-check: the audit anchor folder /mnt/audit has a parent folder / that another account owns or may write: anybod.../.env (the first-run page does not open again: the
- `test_every_start_checks_the_anchor_again`: assert (["the audit anchor folder /mnt/audit has a parent folder / that another account owns or may write: anybody who can wri... around it: set TB_LOG_DIR in deploy/.env to a fold
- `test_in_production_the_anchor_is_the_hospital_s_audit_share_itself[/mnt/nas/backup-is`: 
- `test_in_production_the_anchor_is_the_hospital_s_audit_share_itself[/mnt/self-served`: 
- `test_in_production_the_anchor_is_the_hospital_s_audit_share_itself[/srv/plain-is`: 
- `test_outside_production_a_local_folder_of_its_own_may_be_the_anchor`: Use -v to get more diff
- `test_the_install_s_own_log_folder_and_audit_archive_stay_allowed`: Use -v to get more diff

### tests/unit/test_japan_profile_layer.py (12)

- `test_renaming_a_pinned_literal_in_place_is_not_enough`: + refused: the public key's folder <path> is not there, or it or a folder above it is a link, another account's, or writable by others: nothing was written)
- `test_the_guard_reads_templates_yaml_and_js_but_not_their_comments[services/adapter/mapping/new/site.yaml-#`: 
- `test_the_guard_reads_templates_yaml_and_js_but_not_their_comments[services/console/static/new.js-//`: 
- `test_the_guard_reads_templates_yaml_and_js_but_not_their_comments[services/console/templates/new.html-{#`: 
- `test_the_guard_sees_a_seventeenth_switch_and_names_its_file_and_line[JAPAN`: 
- `test_the_guard_sees_a_seventeenth_switch_and_names_its_file_and_line[def`: 
- `test_the_guard_sees_a_seventeenth_switch_and_names_its_file_and_line[def`: 
- `test_the_guard_sees_a_seventeenth_switch_and_names_its_file_and_line[def`: 
- `test_the_guard_sees_a_seventeenth_switch_and_names_its_file_and_line[def`: 
- `test_the_guard_sees_a_seventeenth_switch_and_names_its_file_and_line[def`: 
- `test_the_guard_sees_a_seventeenth_switch_and_names_its_file_and_line[def`: 
- `test_the_guard_sees_a_seventeenth_switch_and_names_its_file_and_line[def`: 

### tests/unit/test_g1_box_install_run.py (10)

- `test_rehearsal_case[cap]`: +  where 1 = CompletedProcess(args=['<path> did not finish (box-install.sh --firstrun exit 1)\nTB-PHASE ended 2026-11-22T14:01:17Z\nBOX-RUN-DONE\n", stderr='').returncode
- `test_rehearsal_case[gate-401]`: +  where 1 = CompletedProcess(args=['<path> line 329, in <module>\n    g = parts["07g-gate"]\n        ~~~~~^^^^^^^^^^^^\nKeyError: \'07g-gate\'\n').returncode
- `test_rehearsal_case[gate-closed]`: +  where 1 = CompletedProcess(args=['<path> is True and calls["canary-gate once"] == 1,\n    ~~~~~^^^^^^^^^^^^\nKeyError: \'07g-gate\'\n').returncode
- `test_rehearsal_case[gate-never]`: +  where 1 = CompletedProcess(args=['<path> line 329, in <module>\n    g = parts["07g-gate"]\n        ~~~~~^^^^^^^^^^^^\nKeyError: \'07g-gate\'\n').returncode
- `test_rehearsal_case[happy]`: +  where 1 = CompletedProcess(args=['<path> did not finish (box-install.sh --firstrun exit 1)\nTB-PHASE stopped 2026-11-22T14:00:27Z\nBOX-RUN-DONE\n', stderr='').returncode
- `test_rehearsal_case[identity-differs]`: +  where 1 = CompletedProcess(args=['<path>
- `test_rehearsal_case[list-differs]`: +  where 1 = CompletedProcess(args=['<path> did not finish (box-install.sh --firstrun exit 1)\nTB-PHASE stopped 2026-11-22T14:00:18Z\nBOX-RUN-DONE\n', stderr='').returncode
- `test_rehearsal_case[oom]`: +  where 1 = CompletedProcess(args=['<path> is True and calls["canary-gate once"] == 1,\n    ~~~~~^^^^^^^^^^^^\nKeyError: \'07g-gate\'\n').returncode
- `test_rehearsal_case[reboot]`: +  where 1 = CompletedProcess(args=['bash', '<path> (the first-run page does not open again: the answers are applied). Then: sudo deploy/box-install.sh --firstrun\n").returncode
- `test_rehearsal_case[step-fails]`: +  where 1 = CompletedProcess(args=['<path> line 314, in <module>\n    p = parts["08-qualify"]\n        ~~~~~^^^^^^^^^^^^^^\nKeyError: \'08-qualify\'\n').returncode

### tests/console/test_box_install_rehearsal.py (2)

- `test_a_box_installs_from_the_installer_with_only_the_wizards_answers`: +  where 1 = <Popen: returncode: 1 args: ['bash', '<path>
- `test_a_box_installs_from_the_installer_with_only_the_wizards_answers`: +  where 1 = <Popen: returncode: 1 args: ['bash', '<path>

### tests/console/test_firstrun_folders_10k4.py (2)

- `test_a_production_box_does_not_finish_its_set_up_until_its_folders_are_right`: 
- `test_a_production_box_does_not_finish_its_set_up_until_its_folders_are_right`: 

### tests/console/test_health_mail.py (2)

- `test_metrics_for_the_admin_and_the_scraper_only`: ...Full output truncated, use '-vv' to show)
- `test_metrics_for_the_admin_and_the_scraper_only`: ...Full output truncated, use '-vv' to show)

### tests/unit/test_erasure_registry.py (2)

- `test_a_new_lake_folder_is_found`: +  and   1 = min(2, 1)
- `test_a_new_lake_folder_is_found`: +  and   1 = min(2, 1)

### tests/unit/test_refdata.py (1)

- `test_the_tar_is_deterministic_and_safe`: Use -v to get more diff

### tests/unit/test_release_dirty_refused.py (1)

- `test_review_a_first_install_on_a_dev_box_takes_it_and_a_clean_release_goes_on_a_site_box`: 

