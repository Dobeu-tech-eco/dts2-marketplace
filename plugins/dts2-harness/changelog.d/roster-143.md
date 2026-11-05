### Fixed

- roster: `classify_dispatch` treats exit 143 (SIGTERM from `timeout`) as outcome `timeout` with `seatFailed: true`, so council can swap the seat.
