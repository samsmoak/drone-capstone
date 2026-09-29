MISSIONS — the index
====================

Autonomous flight, in two halves that meet at one file:

  floor-plans.txt          WHAT to fly: rooms (geofence, obstacles, coverage),
                           missions (home, inspection points), the agent's
                           validation, saving them on the laptop, the API.
                           backend/agent/cropwatcher/mission/plan/
  mission-controller.txt   HOW it is flown: the mission controller, the goal it
                           gives the manual flight system (fly_to), the
                           session's run_mission, and the inspection point
                           stamped on every reading.
                           backend/agent/cropwatcher/mission/controller/

The desktop page that plans and flies them: ../desktop/auto-control.txt.
What the readings of a mission become: ../pipeline/data-pipeline.txt.
The plan that built all of it: ../../plans/2026-09-28-missions-and-pipeline.txt.
