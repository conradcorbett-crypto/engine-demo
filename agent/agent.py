from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, MessagesState, START
from langgraph.prebuilt import ToolNode, tools_condition
from langsmith import traceable

from agent.prompts import SYSTEM_PROMPT
from agent.tools import TOOLS


def build_agent():
    llm = ChatAnthropic(model="claude-haiku-4-5-20251001", max_tokens=1024).bind_tools(TOOLS)

    def call_model(state: MessagesState, config: RunnableConfig):
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
        return {"messages": [llm.invoke(messages, config)]}

    graph = StateGraph(MessagesState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", ToolNode(TOOLS))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")

    return graph.compile()


def _make_config(extra_metadata: dict = None) -> RunnableConfig:
    metadata = {"demo": "true", "demo_type": "parrot-expert"}
    if extra_metadata:
        metadata.update(extra_metadata)
    return RunnableConfig(
        metadata=metadata,
        tags=["engine-demo", "parrot-agent"],
        run_name="parrot-demo",
    )


@traceable(name="parrot-demo", run_type="chain", tags=["engine-demo", "parrot-agent"])
def invoke_agent(question: str, extra_metadata: dict = None) -> str:
    """Invoke the agent and return the full response string.

    @traceable gives the root LangSmith trace outputs: {"output": "..."},
    which online evaluators can reference via variable_mapping {"output": "output"}.
    """
    agent = build_agent()
    result = agent.invoke(
        {"messages": [{"role": "user", "content": question}]},
        _make_config(extra_metadata),
    )
    for msg in reversed(result["messages"]):
        if hasattr(msg, "content") and isinstance(msg.content, str) and msg.content:
            return msg.content
    return ""


def stream_agent(question: str, extra_metadata: dict = None, thread_id: str = None):
    """Stream the agent response token by token. Yields str chunks.

    Calls invoke_agent internally so every trace — including UI traces — has
    outputs: {"output": "..."} for online evaluators to score.
    thread_id groups conversation turns under one thread in LangSmith.
    """
    kwargs = {}
    if thread_id:
        kwargs["langsmith_extra"] = {"metadata": {"thread_id": thread_id}}
    response = invoke_agent(question, extra_metadata, **kwargs)
    yield from response
