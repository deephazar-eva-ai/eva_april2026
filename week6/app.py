from rich import print
from core.orchestrator import AgenticRAGOrchestrator


if __name__ == "__main__":
    orchestrator = AgenticRAGOrchestrator()

    while True:
        query = input("\nUser > ")

        if query.lower() in ["exit", "quit"]:
            break

        result = orchestrator.process(query)

        print("\n[bold green]Assistant[/bold green]")
        print(result)