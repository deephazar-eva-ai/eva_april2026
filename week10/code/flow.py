"""Session 8 — growing-graph orchestrator.

The agent's loop becomes a NetworkX DiGraph. Each node is a skill; edges
carry typed AgentResult payloads. The graph GROWS at runtime via five
actors: the Planner's seed plan, dynamic successors from any skill,
static `internal_successors` from the yaml, Critic auto-insertion on
edges out of `critic:true` skills, and Planner re-invocation on node
failure (gated by `recovery.plan_recovery`). Perception's tool-blindness
contract from S7 is preserved — Planner names skills, never tools.

Persistence lives in persistence.py; skill execution in skills.py;
failure-policy in recovery.py; sandbox in sandbox.py.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid

import networkx as nx

import memory as memory_svc
from gateway import ensure_gateway
from persistence import SessionStore
from recovery import handle_critic_verdict, plan_recovery
from schemas import AgentResult, NodeState
from skills import SkillRegistry, run_skill

MAX_NODES = 60  # hard cap so a Planner loop cannot grow forever


# ── Graph ────────────────────────────────────────────────────────────────────

class Graph:
    """NetworkX DiGraph wrapper. Nodes are str ids `n:<i>`; each node carries
    `skill`, `inputs` (list of str), and `status`."""

    def __init__(self):
        self.g = nx.DiGraph()
        self._counter = 0

    def add_node(self, skill: str, inputs: list[str], metadata: dict | None = None) -> str:
        self._counter += 1
        nid = f"n:{self._counter}"
        self.g.add_node(nid, skill=skill, inputs=list(inputs),
                        metadata=dict(metadata or {}), status="pending")
        for inp in inputs:
            if inp.startswith("n:") and inp in self.g.nodes:
                self.g.add_edge(inp, nid)
        return nid

    def mark(self, nid: str, status: str) -> None:
        self.g.nodes[nid]["status"] = status

    def ready_nodes(self) -> list[str]:
        # A predecessor counts as "satisfied" when it is either complete or
        # skipped (the latter is how a Critic-fail removes a child from the
        # critical path without blocking unrelated branches downstream).
        out = []
        for nid, d in self.g.nodes(data=True):
            if d["status"] != "pending":
                continue
            preds = list(self.g.predecessors(nid))
            if all(self.g.nodes[p]["status"] in ("complete", "skipped") for p in preds):
                out.append(nid)
        return out

    def has_running(self) -> bool:
        return any(d["status"] == "running" for _, d in self.g.nodes(data=True))

    def extend_from(self, src_nid: str, result: AgentResult,
                    *, registry: SkillRegistry) -> list[str]:
        """Splice in dynamic successors, static internal_successors, and
        critic auto-insertion. Returns the list of new node ids.

        Resolves label-based input references (`n:<label>`) against the
        `metadata.label` of nodes added in the same batch. The Planner is
        encouraged to name its nodes by label so it can reference them
        without knowing the integer ids the orchestrator will hand out."""
        added: list[str] = []
        src_def = registry.get(self.g.nodes[src_nid]["skill"])

        # Pass 1: add the new nodes; build a label → assigned-id map.
        label_to_id: dict[str, str] = {}
        pending: list[tuple[str, list[str]]] = []
        for spec in result.successors:
            label = (spec.metadata or {}).get("label")
            new_id = self.add_node(spec.skill, inputs=[],
                                   metadata=spec.metadata)
            added.append(new_id)
            if isinstance(label, str) and label:
                label_to_id[label] = new_id
            pending.append((new_id, list(spec.inputs)))

        # Pass 2: resolve inputs now that every sibling has an id. Translate
        # `n:<label>` to `n:<assigned-id>` if the label matches; pass numeric
        # `n:<i>` references through; pass anything else through unchanged.
        # NOTE: an empty `raw_inputs` is now a legitimate Planner signal for
        # a fan-out worker scoped via `metadata.question` (see planner.md).
        # We do NOT substitute the parent in that case — doing so would dump
        # the parent's full output (which for the Planner contains every
        # sibling's question) back into the worker's INPUTS block and undo
        # the scoping. The structural parent edge is preserved separately
        # below so the graph topology is still correct.
        for new_id, raw_inputs in pending:
            resolved: list[str] = []
            for inp in raw_inputs:
                # `n:<label>` or `n:<int>` form (preferred).
                if inp.startswith("n:"):
                    suffix = inp[2:]
                    if suffix in label_to_id:
                        resolved.append(label_to_id[suffix])
                        continue
                    if suffix.isdigit() and inp in self.g.nodes:
                        resolved.append(inp)
                        continue
                # Bare label form — the Planner sometimes drops the n: prefix.
                if inp in label_to_id:
                    resolved.append(label_to_id[inp])
                    continue
                # Special literal — the user query is always available.
                if inp == "USER_QUERY":
                    resolved.append(inp)
                    continue
                # Artifact handle — pass through, the input renderer handles it.
                if inp.startswith("art:"):
                    resolved.append(inp)
                    continue
                # Unresolvable input — fall back to the parent so the child
                # has at least one upstream dependency to wait on. This still
                # leaks the parent's output into INPUTS, but only when the
                # Planner emitted a bad input name; it is not the fan-out
                # path. A future round may want to fail loudly here instead.
                resolved.append(src_nid)
            self.g.nodes[new_id]["inputs"] = resolved
            for inp in resolved:
                if inp.startswith("n:") and inp in self.g.nodes:
                    self.g.add_edge(inp, new_id)
            # Fan-out worker case: planner emitted inputs=[] on purpose. No
            # data dependency, but we still record the structural parent
            # edge so the executor's `ready_nodes` ordering and replay
            # topology stay coherent.
            if not raw_inputs:
                self.g.add_edge(src_nid, new_id)

        for child_skill in src_def.internal_successors:
            nid = self.add_node(child_skill, inputs=[src_nid])
            added.append(nid)

        # Critic auto-insertion: when a `critic: true` skill completes,
        # gate every outgoing edge (to a non-critic child) with a Critic
        # node. Covers BOTH newly-added dynamic successors AND pre-existing
        # edges from the initial Planner plan — earlier versions only saw
        # `added`, so a pre-planned distiller → formatter chain bypassed
        # the auto-critic entirely (the `critic: true` flag became a no-op
        # in the common pre-planned case). Reading the graph's actual
        # outgoing edges makes the flag load-bearing in both shapes.
        if src_def.critic:
            child_targets: list[str | None] = []
            has_critic = False
            for child_nid in list(self.g.successors(src_nid)):
                if self.g.nodes[child_nid].get("skill") == "critic":
                    has_critic = True
                    continue  # already gated
                child_targets.append(child_nid)
                
            if not child_targets and not has_critic:
                # Insert a standalone critic even if there are no outgoing edges
                child_targets.append(None)
                
            for child_nid in child_targets:
                if child_nid:
                    self.g.remove_edge(src_nid, child_nid)
                # Critics need USER_QUERY: without it the critic falls back
                # to MEMORY HITS for context (and stale hits from prior
                # sessions can fool the critic into believing the user
                # asked a completely different question). With USER_QUERY
                # the critic evaluates against the real ask and not against
                # whatever happens to be top-of-FAISS.
                # In addition, if it's a distiller, we pass the upstream sub-task (question/goal)
                # so the critic evaluates if the sub-task was actually fulfilled.
                sub_task = None
                if self.g.nodes[src_nid].get("skill") == "distiller":
                    src_meta = self.g.nodes[src_nid].get("metadata") or {}
                    sub_task = src_meta.get("question") or src_meta.get("goal")
                    
                    if not sub_task:
                        for p_nid in self.g.predecessors(src_nid):
                            p_meta = self.g.nodes[p_nid].get("metadata") or {}
                            sub_task = p_meta.get("goal") or p_meta.get("question")
                            if sub_task:
                                break
                            
                critic_meta = {"target": src_nid, "child": child_nid or ""}
                if sub_task:
                    critic_meta["question"] = sub_task

                critic_nid = self.add_node(
                    "critic", inputs=["USER_QUERY", src_nid],
                    metadata=critic_meta,
                )
                if child_nid:
                    self.g.add_edge(critic_nid, child_nid)
                added.append(critic_nid)

        return added


# ── Executor ─────────────────────────────────────────────────────────────────

class Executor:
    def __init__(self, registry: SkillRegistry | None = None, concurrency_limit: int = 2):
        ensure_gateway()
        self.registry = registry or SkillRegistry()
        self.semaphore = asyncio.Semaphore(concurrency_limit)

    async def run(self, query: str, *, session_id: str | None = None,
                  resume: bool = False) -> str:
        sid = session_id or f"s8-{uuid.uuid4().hex[:8]}"
        store = SessionStore(sid)
        if resume:
            existing = store.read_graph()
            if existing is None:
                raise RuntimeError(f"cannot resume {sid}: no graph.pkl on disk")
            graph_obj = existing
            graph = Graph.__new__(Graph)
            graph.g = graph_obj
            graph._counter = max(
                [int(n.split(":")[1]) for n in graph.g.nodes if n.startswith("n:")] or [0]
            )
            for _, d in graph.g.nodes(data=True):
                if d["status"] == "running":
                    d["status"] = "pending"
            if not query:
                query = store.read_query()
        else:
            store.write_query(query)
            graph = Graph()
            graph.add_node("planner", inputs=["USER_QUERY"])

        print(f"\n{'═' * 78}\nsession {sid}  ─  query: {query}\n{'═' * 78}")
        # Read memory ONCE at session start; the same hits flow into every
        # skill's prompt. The S7 contract is that every cognitive role sees
        # memory; carrying that forward verbatim here is what makes S7's
        # indexing investment continue to pay off in S8.
        memory_hits = memory_svc.read(query) or []
        if memory_hits:
            print(f"[memory.read] {len(memory_hits)} hit(s) visible to every skill this run")
        try:
            memory_svc.remember(query, source="user_query", run_id=sid)
        except Exception as e:
            print(f"[memory.remember] skipped: {e!r}")

        formatter_answer: str | None = None
        executed_count = 0
        # Per-target cap for critic-fail recovery; see P1 #5 fix below.
        recovered_branches: dict[str, bool] = {}
        # NOTES_RUNS round-3 review #5: when the cap fires, the branch is
        # skipped silently and the final answer reflects missing data with
        # no flag. Track every second-or-later critic-fail here so the
        # final log can surface it.
        critic_fail_cap_hit: list[str] = []

        from mcp_runner import MultiplexedMCPClient
        from pathlib import Path
        import os
        import shutil
        
        async with MultiplexedMCPClient() as session_mux:
            trajectory_dir = str(Path(__file__).parent / "trajectories" / sid)
            if "start_recording" in session_mux.tool_map:
                try:
                    rec_res = await session_mux.call_tool("start_recording", {"output_dir": trajectory_dir})
                    print(f"DEBUG: start_recording result: {rec_res}")
                    replay_dir = Path(__file__).parent / "replay"
                    os.makedirs(replay_dir, exist_ok=True)
                    source_html = Path(__file__).parent / "trajectory_player.html"
                    if source_html.exists():
                        target_html = replay_dir / f"trajectory_replay_{sid}.html"
                        shutil.copy2(source_html, target_html)
                        try:
                            os.chmod(target_html, 0o666)
                        except Exception:
                            pass
                except Exception as e:
                    print(f"DEBUG: Failed to start recording: {e}")

            try:
                while True:
                    ready = graph.ready_nodes()
                    if not ready and not graph.has_running():
                        break
                    if executed_count + len(ready) > MAX_NODES:
                        print(f"[flow] node cap {MAX_NODES} hit at {executed_count}; stopping")
                        break

                    for nid in ready:
                        graph.mark(nid, "running")
                    store.write_graph(graph.g)

                    async def bounded_run(nid_to_run):
                        async with self.semaphore:
                            return await self._run_one(nid_to_run, graph, sid, query, store, memory_hits)

                    outcomes = await asyncio.gather(*[bounded_run(nid) for nid in ready])

                    for nid, result, prompt in outcomes:
                        executed_count += 1
                        graph.g.nodes[nid]["result"] = result
                        graph.mark(nid, "complete" if result.success else "failed")
                        store.write_node(NodeState(
                            node_id=nid, skill=graph.g.nodes[nid]["skill"],
                            status=graph.g.nodes[nid]["status"],
                            inputs=graph.g.nodes[nid]["inputs"],
                            result=result, prompt_sent=prompt,
                            started_at=time.time() - result.elapsed_s,
                            completed_at=time.time(),
                        ))
                        print(f"[{nid}] {graph.g.nodes[nid]['skill']:18s} "
                              f"{graph.g.nodes[nid]['status']:8s} "
                              f"({result.elapsed_s:.1f}s)"
                              + (f"  err={result.error}" if result.error else ""))

                        if result.success:
                            if graph.g.nodes[nid]["skill"] == "critic":
                                if handle_critic_verdict(nid, result, graph,
                                                         recovered_branches,
                                                         critic_fail_cap_hit):
                                    continue
                                # verdict == pass: the child is now ready to run.
                            graph.extend_from(nid, result, registry=self.registry)
                            if graph.g.nodes[nid]["skill"] == "formatter":
                                fa = result.output.get("final_answer")
                                if isinstance(fa, str) and fa.strip():
                                    formatter_answer = fa
                        else:
                            failed_skill = graph.g.nodes[nid]["skill"]
                            decision = plan_recovery(
                                failed_skill=failed_skill,
                                error_text=result.error or "",
                                failed_node_id=nid,
                            )
                            if decision.action == "skip":
                                print(f"  ↪ {nid} failed ({decision.reason}, "
                                      f"skill={failed_skill}): {decision.note}")
                                continue
                            # action == "replan"
                            # Recovery Planner amnesia fix: pass the ids of nodes that
                            # have already completed successfully so the recovery
                            # Planner can wire them by id in its successor plan
                            # instead of re-emitting fresh fan-out siblings that
                            # duplicate work already done. Excludes planner nodes
                            # (routing context, not data) and critic nodes (verdicts,
                            # not data); their outputs are not useful upstream input
                            # for a recovery plan. planner.md teaches the recovery
                            # Planner what to do with these n:* refs.
                            prior_complete = [
                                n for n, d in graph.g.nodes(data=True)
                                if d.get("status") == "complete"
                                and d["skill"] not in ("planner", "critic")
                                and isinstance(d.get("result"), AgentResult)
                            ]
                            recovery_inputs = ["USER_QUERY"] + prior_complete
                            rec_nid = graph.add_node(
                                "planner", inputs=recovery_inputs,
                                metadata={"failure_report": decision.failure_report,
                                          "recovers": nid,
                                          "recovery_reason": decision.reason,
                                          "prior_complete": prior_complete},
                            )
                            print(f"  ↪ recovery ({decision.reason}): planner node "
                                  f"{rec_nid} queued for {nid}"
                                  + (f"; reusing {len(prior_complete)} prior result(s): "
                                     f"{', '.join(prior_complete)}" if prior_complete else ""))

                    store.write_graph(graph.g)

                if formatter_answer is None:
                    for nid in reversed(list(graph.g.nodes)):
                        d = graph.g.nodes[nid]
                        if d["status"] == "complete" and isinstance(d.get("result"), AgentResult):
                            formatter_answer = json.dumps(d["result"].output)[:2000]
                            break

                if critic_fail_cap_hit:
                    # Loud surface — see review round-3 #5. Without this the cap
                    # firing was invisible and the user would just see a thin
                    # formatter answer with no explanation of why.
                    print(f"\n[flow] WARNING: critic-fail cap hit on "
                          f"{len(critic_fail_cap_hit)} branch(es): "
                          f"{', '.join(critic_fail_cap_hit)}. "
                          f"The final answer reflects missing data from these "
                          f"branches because the Critic rejected the re-planned "
                          f"output too.")
                print(f"\n{'═' * 78}\nFINAL: {(formatter_answer or '')[:600]}\n{'═' * 78}\n")
                final_answer_to_return = formatter_answer or ""
            finally:
                if "stop_recording" in session_mux.tool_map:
                    try:
                        await session_mux.call_tool("stop_recording", {})
                        print("DEBUG: stop_recording called.")
                    except Exception:
                        pass
                    
                    # Fix file permissions for host volume access
                    try:
                        os.system(f"chmod -R 777 {trajectory_dir} {replay_dir}")
                        os.system(f"chown -R 1001:1001 {trajectory_dir} {replay_dir}")
                    except Exception:
                        pass
        await asyncio.sleep(0.1)
        import gc
        gc.collect()
        await asyncio.sleep(0.1)
        return final_answer_to_return

    async def _run_one(self, nid: str, graph: Graph, sid: str, query: str,
                       store: SessionStore, memory_hits: list) -> tuple[str, AgentResult, str]:
        skill_name = graph.g.nodes[nid]["skill"]
        skill = self.registry.get(skill_name)
        fr = graph.g.nodes[nid].get("metadata", {}).get("failure_report")
        store.write_node(NodeState(node_id=nid, skill=skill_name, status="running",
                                   inputs=graph.g.nodes[nid]["inputs"],
                                   started_at=time.time()))
        try:
            result, prompt = await run_skill(skill, nid, graph.g.nodes, sid, query, fr,
                                             memory_hits=memory_hits)
        except Exception as e:  # pragma: no cover - dispatcher fault path
            def get_leaf_errors(exc):
                if isinstance(exc, ExceptionGroup):
                    res = []
                    for child in exc.exceptions:
                        res.extend(get_leaf_errors(child))
                    return res
                import httpx
                if isinstance(exc, httpx.HTTPStatusError):
                    return [f"HTTPStatusError: {exc} - Response: {exc.response.text}"]
                return [f"{type(exc).__name__}: {exc}"]
            err_msg = f"exception: {type(e).__name__}: {e}"
            if isinstance(e, ExceptionGroup):
                sub_errs = ", ".join(get_leaf_errors(e))
                err_msg = f"ExceptionGroup | subs: {sub_errs}"
            result = AgentResult(success=False, agent_name=skill_name,
                                 error=err_msg)
            prompt = "(exception before prompt-render)"
        return nid, result, prompt


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]
    resume_sid: str | None = None
    if args and args[0] == "--resume":
        resume_sid = args[1] if len(args) > 1 else None
        query = " ".join(args[2:])
    else:
        query = " ".join(args) or "Say hello in one short sentence."
    asyncio.run(Executor().run(query, session_id=resume_sid, resume=bool(resume_sid)))
    
    # Suppress noisy asyncio __del__ tracebacks during interpreter shutdown
    import os
    sys.stderr = open(os.devnull, 'w')


if __name__ == "__main__":
    main()
