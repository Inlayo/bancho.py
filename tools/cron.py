from __future__ import annotations

import logging
import os
import time

os.environ["SQLALCHEMY_SILENCE_UBER_WARNING"] = "1"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
env_file_path = "/home/ubuntu/bancho.py/.env"


def read_env_file():
    with open(env_file_path) as file:
        return file.readlines()


def write_env_file(lines):
    with open(env_file_path, "w") as file:
        file.writelines(lines)


def modify_env_variables():
    lines = read_env_file()
    for i, line in enumerate(lines):
        if line.startswith("DB_HOST"):
            lines[i] = "DB_HOST=localhost\n"
        elif line.startswith("REDIS_HOST"):
            lines[i] = "REDIS_HOST=localhost\n"
    write_env_file(lines)
    logging.info("Modified environment variables to localhost.")


def restore_env_variables():
    lines = read_env_file()
    for i, line in enumerate(lines):
        if line.startswith("DB_HOST"):
            lines[i] = "DB_HOST=mysql\n"
        elif line.startswith("REDIS_HOST"):
            lines[i] = "REDIS_HOST=redis\n"
    write_env_file(lines)
    logging.info("Restored environment variables to original settings.")


def run_script():
    logging.info("Starting script execution...")

    start_time = time.time()

    modify_env_variables()

    try:
        logging.info("Executing recalc.py...")
        exit_code = os.system("python recalc.py")
        if exit_code != 0:
            logging.error(f"recalc.py execution failed with exit code {exit_code}")
        else:
            logging.info("recalc.py executed successfully.")
    except Exception as e:
        logging.error(f"An error occurred while running recalc.py: {e}")
    finally:
        restore_env_variables()

    elapsed_time = time.time() - start_time
    logging.info(f"Script executed in {elapsed_time:.2f} seconds.")


run_script()
