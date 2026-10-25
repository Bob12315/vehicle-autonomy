"""Mission Studio and Control Center for explicit, owned local simulations."""
from vehicle_autonomy.app.web.action_cli import main as run

def main():
    return run(studio=True)

if __name__ == '__main__': raise SystemExit(main())
