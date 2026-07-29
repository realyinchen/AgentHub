"""Compatibility entrypoint for the pre-commit memory architecture verifier.

The former raw-first/pending workflow was intentionally retired. Keep this
script name so existing developer commands exercise the replacement contract
instead of validating obsolete behavior.
"""

from verify_memory_precommit_flow import main


if __name__ == "__main__":
    main()
