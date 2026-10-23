"""Claude Code hooks: the data guard, frozen-file guard, write validator and session brief.

Every module here is imported on every hook call, so none imports pydantic (or any other
heavy module) at module level; vault configuration is loaded only once a vault is found.
"""
