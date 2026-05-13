from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, MessagesState, START
from langgraph.prebuilt import ToolNode, tools_condition

from agent.prompts import SYSTEM_PROMPT
from agent.tools import TOOLS


def build_agent():
    llm = ChatAnthropic(model="claude-haiku-4-5-20251001", max_tokens=1500).bind_tools(TOOLS)

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
    metadata = {"demo": "true", "demo_type": "pocket-polly"}
    if extra_metadata:
        metadata.update(extra_metadata)
    return RunnableConfig(
        run_name="pocket-polly-demo",
        metadata=metadata,
        tags=["engine-demo", "pocket-polly-agent"],
    )


def invoke_agent(question: str, extra_metadata: dict = None, thread_id: str = None) -> dict:
    """Invoke the agent and return the full conversation as messages plus a flat tools_called list.

    The messages list (input, tool calls, tool results, final response) is stored
    in run.outputs so the trace shows the complete trajectory.
    tools_called is a flat list of tool names so evaluators can check it directly.
    """
    agent = build_agent()
    merged_metadata = {**(extra_metadata or {})}
    if thread_id:
        merged_metadata["thread_id"] = thread_id
    result = agent.invoke(
        {"messages": [{"role": "user", "content": question}]},
        _make_config(merged_metadata or None),
    )
    output = ""
    for msg in reversed(result["messages"]):
        if hasattr(msg, "content") and isinstance(msg.content, str) and msg.content:
            output = msg.content
            break
    tools_called = [msg.name for msg in result["messages"] if isinstance(msg, ToolMessage)]
    return {
        "output": output,
        "messages": result["messages"],
        "tools_called": tools_called,
    }


def stream_agent(question: str, extra_metadata: dict = None, thread_id: str = None):
    """Stream the agent response token by token. Yields str chunks."""
    result = invoke_agent(question, extra_metadata, thread_id=thread_id)
    yield from result["output"]
