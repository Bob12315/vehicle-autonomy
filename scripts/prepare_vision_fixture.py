#!/usr/bin/env python3
"""Explicit setup entry; ordinary startup never downloads vision assets."""
from vehicle_autonomy.app.bootstrap.vision_fixture import main

if __name__ == "__main__":
    main()
