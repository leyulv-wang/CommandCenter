from langgraph.graph import END, START, StateGraph

from app.agent.nodes import (
    build_api_payload_node,
    build_form_values_node,
    load_form_config,
    submit_external_api_node,
    validate_submission_node,
)
from app.agent.state import FormExecutionState


def build_graph():
    graph = StateGraph(FormExecutionState)
    graph.add_node("load_form_config", load_form_config)
    graph.add_node("validate_submission", validate_submission_node)
    graph.add_node("build_form_values", build_form_values_node)
    graph.add_node("build_api_payload", build_api_payload_node)
    graph.add_node("submit_external_api", submit_external_api_node)

    graph.add_edge(START, "load_form_config")
    graph.add_edge("load_form_config", "validate_submission")
    graph.add_edge("validate_submission", "build_form_values")
    graph.add_edge("build_form_values", "build_api_payload")
    graph.add_edge("build_api_payload", "submit_external_api")
    graph.add_edge("submit_external_api", END)
    return graph.compile()


form_execution_graph = build_graph()
