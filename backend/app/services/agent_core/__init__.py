"""Agent Core package.

Import contracts and services from their owning leaf modules.  Keeping this
package entry point inert prevents task/runtime imports from depending on an
accidental eager-import order.
"""
