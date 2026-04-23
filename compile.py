import solcx
import os

# Ensure solc 0.8.20 is installed
if "0.8.20" not in [str(v) for v in solcx.get_installed_solc_versions()]:
    solcx.install_solc("0.8.20")

solcx.set_solc_version("0.8.20")


def compile_contract(path: str) -> tuple:
    """
    Compiles a .sol file and returns (abi, bytecode_hex).
    """
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()

    contract_name = os.path.splitext(os.path.basename(path))[0]

    compiled = solcx.compile_source(
        source,
        output_values=["abi", "bin"],
        solc_version="0.8.20",
    )

    # Find the contract in compiled output
    contract_key = None
    for key in compiled:
        if key.endswith(f":{contract_name}"):
            contract_key = key
            break

    if contract_key is None:
        for key in compiled:
            if compiled[key]["bin"]:
                contract_key = key
                break

    if contract_key is None:
        raise ValueError(f"Could not find compiled contract in {path}")

    abi = compiled[contract_key]["abi"]
    bytecode = compiled[contract_key]["bin"]
    return abi, bytecode
