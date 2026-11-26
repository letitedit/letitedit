"""letitedit Studio: make things from a written job (job.json in a folder), for other programs.

The contract is contract/CONTRACT.md, its schemas contract/schemas, its examples contract/examples. The command line is
bridge/letitedit_studio.py (cli.py); the Python functions are in service.py: validate, submit, status, cancel, retry,
run. fake.py is the reference fake callers test against; contract/tests/contract_tests.py checks either.
"""
