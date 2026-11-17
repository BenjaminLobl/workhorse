# Historical 0.3.1 → 0.4 installer

The material under [companion-to-workplace](companion-to-workplace/) is the original Workplace 0.4 migration, kept apart from current application code. Its payloads and baseline fixtures must retain their original bytes: the installer checks hashes and patches exact source blocks. Do not run it against this refactored checkout.

To use the historical migration, stop Workhorse and run `Apply-Workplace-Upgrade.cmd` from that directory. For a fresh installation of current source, use [Setup.cmd](../Setup.cmd) at the repository root.

To verify the migration independently, run from the repository root:

```shell
python maintenance/companion-to-workplace/upgrade_tests/test_installer.py -v
```
