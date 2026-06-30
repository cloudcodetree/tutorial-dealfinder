"""A tiny ReAct-style agent: a loop of think → act (call a tool) → observe.

The *policy* (what to do next) is pluggable. Tests use a scripted policy so the
loop is fully deterministic and offline; in production the policy is an LLM
(LangGraph) that reads the trace and decides the next tool. The loop, the tool
registry, and the human-in-the-loop gate are identical either way.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Tool:
    name: str
    fn: Callable
    description: str = ""
    requires_approval: bool = False


@dataclass
class Action:
    thought: str
    tool: str | None                       # None => finish
    args: dict = field(default_factory=dict)
    answer: Any = None                      # set when finishing


@dataclass
class Step:
    thought: str
    tool: str | None
    args: dict
    observation: Any = None


class Agent:
    def __init__(self, tools, policy, approve: Callable | None = None, max_steps: int = 8):
        self.tools = {t.name: t for t in tools}
        self.policy = policy
        self.approve = approve or (lambda name, args: True)
        self.max_steps = max_steps

    def run(self, goal: str):
        trace: list[Step] = []
        for _ in range(self.max_steps):
            action = self.policy(goal, trace)
            if action.tool is None:                     # finish
                trace.append(Step(action.thought, None, {}, action.answer))
                return action.answer, trace
            tool = self.tools[action.tool]
            if tool.requires_approval and not self.approve(action.tool, action.args):
                trace.append(Step(action.thought, action.tool, action.args, "BLOCKED: needs human approval"))
                continue
            obs = tool.fn(**action.args)
            trace.append(Step(action.thought, action.tool, action.args, obs))
        return None, trace
