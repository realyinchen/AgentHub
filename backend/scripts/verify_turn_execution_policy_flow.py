"""Compatibility entry for the unified ActionPlan runtime verification.

TurnExecution is now decision-only. Execution policy is verified through the
ActionPlan -> SystemRuntime -> PlanReceipt flow.
"""

from verify_agent_runtime_adaptive_flow import main


if __name__ == "__main__":
    main()
