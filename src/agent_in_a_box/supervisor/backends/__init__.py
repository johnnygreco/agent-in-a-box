"""Backend packages. Each is self-contained behind contracts.SupervisorBackend.

Core packages never import a backend; composition.py registers them by name.
No backend imports another (PLAN.md, Backend module boundary).
"""
