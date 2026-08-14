"""Frutiger Aero motion: splash, transitions, and background scene effects.

Kept isolated from screen logic -- ``ui/screens/*.py`` shouldn't need to
import Qt animation classes directly, only call into modules here. Every
effect checks ``motion.reduced_motion(services)`` before starting and skips
straight to its end state when it's on.
"""
