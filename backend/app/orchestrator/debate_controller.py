"""Debate node control flow for the Karesansui orchestrator.

Implements the round-robin debate loop described in requirement_specification.md §5:

  1. Iterate through all participant agents (Advocate, Disrupter, etc.) in turn.
  2. After every round of participants, the Mediator evaluates whether consensus
     has been reached by returning a Boolean ``consensus_reached`` flag.
  3. When ``consensus_reached`` is True the loop exits and the Mediator's final
     conclusion is forwarded to subsequent DAG tasks.
  4. If the global ``max_debate_rounds`` limit is reached before natural consensus,
     the Mediator is given a forced-exit prompt and is required to emit a
     conclusive summary regardless.  The loop then terminates.

Per-turn History rows (one per participant per round, one per Mediator per round)
are written directly inside this module.  The outer
:class:`~app.orchestrator.manager.OrchestratorManager` writes a single summary
row for the entire debate node after this controller returns.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from celery.result import AsyncResult
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import GlobalSettings, History
from app.orchestrator.dag_parser import DagNode
from app.schemas import DebateParticipantResponse, MediatorResponse
from app.worker import celery_app

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration constants (overridable via environment variables)
# ---------------------------------------------------------------------------

_DEFAULT_MAX_ROUNDS: int = max(1, int(os.environ.get("MAX_DEBATE_ROUNDS", "5")))
_DEFAULT_TASK_TIMEOUT: float = float(os.environ.get("ORCHESTRATOR_TASK_TIMEOUT", "300"))

_TASK_NAME = "app.tasks.run_structured_inference"
_PARTICIPANT_CLASS_PATH = "app.schemas.DebateParticipantResponse"
_MEDIATOR_CLASS_PATH = "app.schemas.MediatorResponse"


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------


class DebateController:
    """Runs the round-robin debate loop for a single ``Debate``-type DAG node.

    Parameters
    ----------
    model:
        Model identifier forwarded to every inference task.
    system_prompt_template:
        Format string with a ``{role}`` placeholder used to build each
        agent's system prompt.
    task_timeout:
        Per-call wait timeout in seconds for Celery task results.
    db_session:
        Optional pre-wired SQLAlchemy session.  If ``None``, an independent
        session is opened and closed for each DB write.
    temperature:
        Sampling temperature forwarded to all inference tasks.
    max_tokens:
        Maximum tokens forwarded to all inference tasks.
    """

    def __init__(
        self,
        *,
        model: str,
        system_prompt_template: str = "You are a {role} agent.",
        task_timeout: float = _DEFAULT_TASK_TIMEOUT,
        db_session: Session | None = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        run_id: str | None = None,
    ) -> None:
        self._model = model
        self._system_prompt_template = system_prompt_template
        self._task_timeout = task_timeout
        self._db_session = db_session
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._run_id = run_id

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(
        self,
        node: DagNode,
        parent_results: dict[str, Any],
        user_query: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Execute the full debate for *node*; return ``(final_result, progress)``.

        Parameters
        ----------
        node:
            The ``Debate``-type :class:`~app.orchestrator.dag_parser.DagNode`
            being executed.
        parent_results:
            ``{task_id: result}`` mapping of already-completed parent tasks whose
            ``result`` dicts form the pre-debate context injected into every
            agent's prompt.
        user_query:
            The original user query carried through the entire orchestration run.

        Returns
        -------
        tuple[dict, dict]
            ``final_result``
                The Mediator's final structured output (``consensus_reached``
                removed).  This is what child DAG tasks will receive as context.
            ``progress``
                A summary dict containing the full debate transcript, total
                rounds executed, and whether the exit was forced.  Persisted by
                the outer manager to the debate node's History row.
        """
        max_rounds = self._get_max_rounds()
        debate_history: list[dict[str, Any]] = []
        final_result: dict[str, Any] = {}
        exited_naturally = False
        current_round = 1

        for round_num in range(1, max_rounds + 1):
            current_round = round_num
            forced = round_num == max_rounds

            logger.info(
                "[debate] task_id=%r starting round %d/%d (forced=%s)",
                node.task_id, round_num, max_rounds, forced,
            )

            # ---- Participant turns (round-robin) -----
            for participant_role in node.participants:
                participant_result, participant_progress = self._run_participant(
                    node=node,
                    participant_role=participant_role,
                    parent_results=parent_results,
                    debate_history=debate_history,
                    user_query=user_query,
                    round_num=round_num,
                )
                debate_history.append(
                    {"role": participant_role, "round": round_num, **participant_result}
                )
                self._persist_turn(
                    node=node,
                    role=participant_role,
                    round_num=round_num,
                    result=participant_result,
                    worker_progress=participant_progress,
                )
                logger.info(
                    "[debate] task_id=%r round=%d participant=%r done",
                    node.task_id, round_num, participant_role,
                )

            # ---- Mediator evaluation -----
            mediator_result, mediator_progress = self._run_mediator(
                node=node,
                parent_results=parent_results,
                debate_history=debate_history,
                user_query=user_query,
                round_num=round_num,
                forced=forced,
            )
            debate_history.append(
                {"role": node.mediator, "round": round_num, **mediator_result}
            )
            self._persist_turn(
                node=node,
                role=node.mediator or "Mediator",
                round_num=round_num,
                result=mediator_result,
                worker_progress=mediator_progress,
            )
            logger.info(
                "[debate] task_id=%r round=%d mediator consensus_reached=%s",
                node.task_id, round_num, mediator_result.get("consensus_reached"),
            )

            # Strip the control flag from the forwarded result.
            final_result = {
                k: v for k, v in mediator_result.items() if k != "consensus_reached"
            }

            if forced:
                # Max rounds reached; forced-exit summary already generated.
                # Do NOT set exited_naturally regardless of consensus_reached so
                # that forced_exit=True is correctly written to the summary row.
                break
            consensus = bool(mediator_result.get("consensus_reached", False))
            if consensus:
                exited_naturally = True
                break

        progress: dict[str, Any] = {
            "debate_history": debate_history,
            "total_rounds": current_round,
            "forced_exit": not exited_naturally,
        }

        logger.info(
            "[debate] task_id=%r finished; total_rounds=%d forced_exit=%s",
            node.task_id, current_round, not exited_naturally,
        )
        return final_result, progress

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_max_rounds(self) -> int:
        """Read ``max_debate_rounds`` from GlobalSettings, falling back to env/default.

        The DB value may be stored as:
          - an integer directly: ``5``
          - a dict with a ``"rounds"`` key: ``{"rounds": 5}``
        """
        close_session = False
        session: Session = self._db_session  # type: ignore[assignment]
        if session is None:
            session = SessionLocal()
            close_session = True
        try:
            record = session.get(GlobalSettings, "max_debate_rounds")
            if record is not None:
                value = record.value
                if isinstance(value, dict) and "rounds" in value:
                    return max(1, int(value["rounds"]))
                if isinstance(value, (int, float)):
                    return max(1, int(value))
        except Exception:  # noqa: BLE001
            logger.warning(
                "[debate] Could not read max_debate_rounds from DB; using default=%d.",
                _DEFAULT_MAX_ROUNDS,
            )
        finally:
            if close_session:
                session.close()
        return max(1, _DEFAULT_MAX_ROUNDS)

    def _build_participant_messages(
        self,
        node: DagNode,
        participant_role: str,
        parent_results: dict[str, Any],
        debate_history: list[dict[str, Any]],
        user_query: str,
        round_num: int,
    ) -> list[dict[str, str]]:
        """Build the OpenAI-format message list for a participant agent.

        Context injection order
        -----------------------
        1. System prompt with role + dynamic params + round context.
        2. Original user query.
        3. Pre-debate parent task results (token-efficient, result-only).
        4. Accumulated debate transcript (all previous turns, current round included).
        """
        system_content = self._system_prompt_template.format(role=participant_role)
        if node.dynamic_params:
            params_str = "; ".join(
                f"{k}={v!r}" for k, v in node.dynamic_params.items()
            )
            system_content += f"\nParameters: {params_str}"
        system_content += (
            "\nRespond with a flat JSON object. "
            "The object must have EXACTLY two top-level keys:\n"
            '  "argument": your main argument as a string\n'
            '  "support_points": an array of 2-4 strings of supporting evidence\n'
            "Output nothing else — no wrapper, no extra keys."
        )

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_query},
        ]

        if parent_results:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Context from preceding tasks:\n"
                        + json.dumps(parent_results, ensure_ascii=False, indent=2)
                    ),
                }
            )

        if debate_history:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Current debate transcript (previous turns):\n"
                        + json.dumps(debate_history, ensure_ascii=False, indent=2)
                    ),
                }
            )

        messages.append(
            {
                "role": "user",
                "content": (
                    'Respond with a JSON object that has exactly two keys: '
                    '"argument" (string) and "support_points" (array of strings). '
                    'No other keys, no outer wrapper.'
                ),
            }
        )

        return messages

    def _build_mediator_messages(
        self,
        node: DagNode,
        parent_results: dict[str, Any],
        debate_history: list[dict[str, Any]],
        user_query: str,
        round_num: int,
        forced: bool,
    ) -> list[dict[str, str]]:
        """Build the OpenAI-format message list for the Mediator agent.

        When *forced* is True, an explicit directive is appended to the system
        prompt instructing the Mediator to produce a conclusive summary and set
        ``consensus_reached=true`` regardless of whether natural agreement was
        reached.
        """
        mediator_role = node.mediator or "Mediator"
        system_content = self._system_prompt_template.format(role=mediator_role)
        if node.dynamic_params:
            params_str = "; ".join(
                f"{k}={v!r}" for k, v in node.dynamic_params.items()
            )
            system_content += f"\nParameters: {params_str}"

        if forced:
            system_content += (
                "\nThe debate has reached its maximum round limit. "
                "You must produce a conclusive synthesis. "
                "Respond with a flat JSON object that has EXACTLY these three top-level keys:\n"
                '  "consensus_reached": true (boolean)\n'
                '  "conclusion": your synthesis as a string\n'
                '  "reasoning": your reasoning as a string\n'
                "Output nothing else — no wrapper, no extra keys."
            )
        else:
            system_content += (
                "\nReview the debate transcript and evaluate whether consensus has been reached. "
                "Respond with a flat JSON object that has EXACTLY these three top-level keys:\n"
                '  "consensus_reached": true if consensus is reached, false otherwise (boolean)\n'
                '  "conclusion": your conclusion or synthesis as a string\n'
                '  "reasoning": your reasoning as a string\n'
                "Output nothing else — no wrapper, no extra keys."
            )

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_query},
        ]

        if parent_results:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Context from preceding tasks:\n"
                        + json.dumps(parent_results, ensure_ascii=False, indent=2)
                    ),
                }
            )

        messages.append(
            {
                "role": "user",
                "content": (
                    "Full debate transcript so far:\n"
                    + json.dumps(debate_history, ensure_ascii=False, indent=2)
                ),
            }
        )

        messages.append(
            {
                "role": "user",
                "content": (
                    'Respond with a JSON object that has exactly three keys: '
                    '"consensus_reached" (boolean), "conclusion" (string), "reasoning" (string). '
                    'No other keys, no outer wrapper.'
                ),
            }
        )

        return messages

    def _run_participant(
        self,
        *,
        node: DagNode,
        participant_role: str,
        parent_results: dict[str, Any],
        debate_history: list[dict[str, Any]],
        user_query: str,
        round_num: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Enqueue and wait for a single participant agent inference task.

        Returns
        -------
        tuple[dict, dict]
            ``(result_dict, progress_dict)`` – both fields from the worker envelope.
        """
        messages = self._build_participant_messages(
            node=node,
            participant_role=participant_role,
            parent_results=parent_results,
            debate_history=debate_history,
            user_query=user_query,
            round_num=round_num,
        )
        schema = DebateParticipantResponse.model_json_schema()
        async_result: AsyncResult = celery_app.send_task(
            _TASK_NAME,
            kwargs={
                "model": self._model,
                "messages": messages,
                "response_model_schema": schema,
                "response_model_class_path": _PARTICIPANT_CLASS_PATH,
                "temperature": self._temperature,
                "max_tokens": self._max_tokens,
            },
        )
        task_output: dict[str, Any] = async_result.get(
            timeout=self._task_timeout, propagate=True
        )
        return task_output["result"], task_output.get("progress") or {}

    def _run_mediator(
        self,
        *,
        node: DagNode,
        parent_results: dict[str, Any],
        debate_history: list[dict[str, Any]],
        user_query: str,
        round_num: int,
        forced: bool,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Enqueue and wait for the Mediator agent's consensus evaluation task.

        Returns
        -------
        tuple[dict, dict]
            ``(result_dict, progress_dict)`` – both fields from the worker envelope.
        """
        messages = self._build_mediator_messages(
            node=node,
            parent_results=parent_results,
            debate_history=debate_history,
            user_query=user_query,
            round_num=round_num,
            forced=forced,
        )
        schema = MediatorResponse.model_json_schema()
        async_result: AsyncResult = celery_app.send_task(
            _TASK_NAME,
            kwargs={
                "model": self._model,
                "messages": messages,
                "response_model_schema": schema,
                "response_model_class_path": _MEDIATOR_CLASS_PATH,
                "temperature": self._temperature,
                "max_tokens": self._max_tokens,
            },
        )
        task_output: dict[str, Any] = async_result.get(
            timeout=self._task_timeout, propagate=True
        )
        return task_output["result"], task_output.get("progress") or {}

    def _persist_turn(
        self,
        node: DagNode,
        role: str,
        round_num: int,
        result: dict[str, Any],
        worker_progress: dict[str, Any] | None = None,
    ) -> None:
        """Write a single debate turn to the History table.

        Uses a compound ``task_id`` of the form
        ``"{node.task_id}:round{round_num}:{role}"`` so each turn is uniquely
        addressable while remaining associated with the parent debate node.

        ``worker_progress`` is the ``progress`` envelope returned by the Celery
        task (contains ``messages``, ``model``, ``temperature``, ``max_tokens``).
        It is merged with the debate metadata so both operational context and
        inference parameters are preserved in the same row.
        """
        close_session = False
        session: Session = self._db_session  # type: ignore[assignment]
        if session is None:
            session = SessionLocal()
            close_session = True
        try:
            turn_task_id = f"{node.task_id}:round{round_num}:{role}"
            # Merge debate metadata into the worker progress dict so both the
            # operational context (parent node, round) and inference parameters
            # (model, messages, temperature, max_tokens) are retained.
            progress_payload: dict[str, Any] = {
                "parent_task_id": node.task_id,
                "round": round_num,
                **(worker_progress or {}),
            }
            row = History(
                run_id=self._run_id,
                task_id=turn_task_id,
                role=role,
                result=result,
                progress=progress_payload,
            )
            session.add(row)
            session.commit()
        except Exception:  # noqa: BLE001
            logger.exception(
                "[debate] Failed to persist turn task_id=%r role=%r round=%d",
                node.task_id,
                role,
                round_num,
            )
            session.rollback()
        finally:
            if close_session:
                session.close()
