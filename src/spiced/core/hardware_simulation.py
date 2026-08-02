"""Cross-Platform Test Simulation: estimate performance on hardware you don't own.

Spiced has no access to real low-end PC or handheld hardware, so this is a
documented, deterministic estimate — not a real device test. It scales the
fps you actually measured (presumably on your own dev machine) by a fixed
factor per hardware tier and flags locations that would likely dip below a
playable frame rate. The caveat is carried alongside every result.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from spiced.core.performance_parser import ParsedPerformance

PLAYABLE_FPS = 30

# Rough, documented scaling factors relative to the machine the numbers were
# captured on. These are illustrative estimates for planning, not benchmarks.
HARDWARE_TIERS: dict[str, dict] = {
    "Low-end PC": {"fps_factor": 0.5, "memory_factor": 1.3},
    "Mid-range PC": {"fps_factor": 0.75, "memory_factor": 1.1},
    "Handheld (Switch-like)": {"fps_factor": 0.35, "memory_factor": 1.6},
}

CAVEAT = (
    "This is a simulation based on your measured numbers, not a real device test. "
    "Treat it as a planning signal and confirm on real hardware before relying on it."
)


@dataclass
class SimulatedSample:
    location: str
    measured_fps: float
    estimated_fps: float
    at_risk: bool


@dataclass
class HardwareSimulationResult:
    tier: str
    playable_fps: int
    samples: list[SimulatedSample] = field(default_factory=list)
    caveat: str = CAVEAT

    @property
    def at_risk_samples(self) -> list[SimulatedSample]:
        return [s for s in self.samples if s.at_risk]

    def as_summary_dict(self) -> dict:
        return {
            "tier": self.tier,
            "playable_fps": self.playable_fps,
            "at_risk": [
                {
                    "location": s.location,
                    "measured_fps": s.measured_fps,
                    "estimated_fps": s.estimated_fps,
                }
                for s in self.at_risk_samples
            ],
            "caveat": self.caveat,
        }


def available_tiers() -> list[str]:
    return list(HARDWARE_TIERS)


def simulate_hardware(parsed: ParsedPerformance, tier: str) -> HardwareSimulationResult | None:
    settings = HARDWARE_TIERS.get(tier)
    if settings is None:
        return None
    fps_factor = settings["fps_factor"]
    samples = []
    for sample in parsed.samples:
        if sample.fps is None:
            continue
        estimated = round(sample.fps * fps_factor, 1)
        samples.append(
            SimulatedSample(
                location=sample.location,
                measured_fps=sample.fps,
                estimated_fps=estimated,
                at_risk=estimated < PLAYABLE_FPS,
            )
        )
    return HardwareSimulationResult(tier=tier, playable_fps=PLAYABLE_FPS, samples=samples)
