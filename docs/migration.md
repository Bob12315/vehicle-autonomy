# Historical application and future migration

`legacy/cuadc_2026/` contains the previous repository tree, including the
production `SystemRunner`, Action Mission implementation, Web UI, telemetry
link, RKNN application, configuration, tests, scripts, and historical docs.
The archive keeps the original relative paths. From that directory, its
offline test suite still reports `769 passed`.

The new root does not run or import the archive. Reusing an archived module is
a new migration task: identify its owner, move a copy into the appropriate root
package, adapt dependencies to contracts, verify behavior, and delete the
archived copy only when its historical value is no longer needed. Git history
also retains the pre-archive source.

Real vehicle, server, camera, perception, and CUADC scenario integrations are
outside the current root. Before a real vehicle connection, implement and
test the unique writer, authorization lifecycle, Safety parity, explicit
continuous command stop/zero, stale command cancellation, and failure handling.
The old Safety pipeline must not be bypassed by a superficial port adapter.
