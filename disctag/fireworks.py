from __future__ import annotations

import math
import random
import tkinter as tk
from dataclasses import dataclass


@dataclass
class Particle:
    item: int
    x: float
    y: float
    vx: float
    vy: float
    age: int
    life: int
    radius: float


class Fireworks:
    def __init__(self, canvas: tk.Canvas, width: int, height: int, scale: float = 1.0):
        self.canvas = canvas
        self.width = width
        self.height = height
        self.scale = max(0.75, scale)
        self.particles: list[Particle] = []
        self.timers: set[str] = set()
        self.after_id: str | None = None
        self.running = False
        self.colors = ("#6857E5", "#D6A94A", "#16B8AE", "#E46B78", "#8D78FF", "#F0C96A")

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        schedule = (
            (120, 0.18, 0.24),
            (520, 0.52, 0.18),
            (960, 0.82, 0.28),
            (1500, 0.34, 0.34),
            (2100, 0.68, 0.16),
        )
        for delay, x, y in schedule:
            self._schedule(delay, lambda x=x, y=y: self.burst(self.width * x, self.height * y))
        self._animate()

    def burst(self, x: float, y: float) -> None:
        if not self.running:
            return
        for _ in range(38):
            angle = random.uniform(0, math.tau)
            speed = random.uniform(1.4, 5.2) * self.scale
            radius = random.uniform(1.8, 3.8) * self.scale
            item = self.canvas.create_oval(
                x - radius,
                y - radius,
                x + radius,
                y + radius,
                fill=random.choice(self.colors),
                outline="",
            )
            self.particles.append(
                Particle(
                    item=item,
                    x=x,
                    y=y,
                    vx=math.cos(angle) * speed,
                    vy=math.sin(angle) * speed - 1.2 * self.scale,
                    age=0,
                    life=random.randint(38, 72),
                    radius=radius,
                )
            )

    def stop(self) -> None:
        self.running = False
        for timer in self.timers:
            self.canvas.after_cancel(timer)
        self.timers.clear()
        if self.after_id:
            self.canvas.after_cancel(self.after_id)
            self.after_id = None
        for particle in self.particles:
            self.canvas.delete(particle.item)
        self.particles.clear()

    def _schedule(self, delay: int, callback) -> None:
        timer = self.canvas.after(delay, lambda: self._run_timer(timer, callback))
        self.timers.add(timer)

    def _run_timer(self, timer: str, callback) -> None:
        self.timers.discard(timer)
        if self.running:
            callback()

    def _animate(self) -> None:
        if not self.running:
            return
        alive = []
        gravity = 0.075 * self.scale
        for particle in self.particles:
            particle.age += 1
            if particle.age > particle.life:
                self.canvas.delete(particle.item)
                continue
            particle.vx *= 0.992
            particle.vy = particle.vy * 0.992 + gravity
            particle.x += particle.vx
            particle.y += particle.vy
            fade = max(0.2, 1 - particle.age / particle.life)
            radius = particle.radius * fade
            self.canvas.coords(
                particle.item,
                particle.x - radius,
                particle.y - radius,
                particle.x + radius,
                particle.y + radius,
            )
            alive.append(particle)
        self.particles = alive
        self.after_id = self.canvas.after(20, self._animate)
