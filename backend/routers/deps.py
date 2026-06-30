"""Dipendenze condivise per controllo accesso nodi."""

from fastapi import HTTPException

from database import Node, User


def check_node_access(user: User, node: Node) -> bool:
    """Verifica se l'utente può accedere al nodo."""
    if user.role == "admin":
        return True
    if user.allowed_nodes is None:
        return True
    return node.id in user.allowed_nodes


def assert_node_access(user: User, node: Node) -> None:
    """Solleva 403 se l'utente non può accedere al nodo."""
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato al nodo")


def filter_nodes_for_user(user: User, nodes: list) -> list:
    """Filtra una lista di nodi in base a allowed_nodes."""
    if user.role == "admin" or user.allowed_nodes is None:
        return nodes
    allowed = set(user.allowed_nodes)
    return [n for n in nodes if n.id in allowed]
