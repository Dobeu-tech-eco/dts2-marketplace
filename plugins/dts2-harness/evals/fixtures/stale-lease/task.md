# Stale lease
Spec: a lane is leased twice (epoch 2). A late writer that still holds epoch 1 must be refused, and the stored
lease must keep epoch 2. The build itself is a single green round.
