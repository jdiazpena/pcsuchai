# Native deployment cache

`scripts/install_rpi.sh` stores verified ApexPy source archives under
`vendor/sources/` and reusable native wheels under
`vendor/wheels/<architecture>-<python-tag>/`.

Do not rename a wheel to suggest another architecture or Python ABI. The
installer deliberately ignores incompatible directories. A release bundle may
include compatible cached wheels so its operator does not have to rebuild
ApexPy.
