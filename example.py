#!/usr/bin/env python3
import os
import sys
import time
import logging
import subprocess
import ssl
import json
import xmlrpc.client as xmlrpc_client
import xmltodict  # pip install xmltodict

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")

PACKAGE_VERSION = 0.1

# Read credentials from environment variables.
try:
    LOGIN_ID  = os.environ['USER']
    PEM_PWORD = os.environ['PWORD']
    CERT_PATH = os.environ['CERT']
except KeyError:
    logging.error("Missing CloudLab credential environment variables (USER, PWORD, CERT)")
    sys.exit(1)

XMLRPC_SERVER = "boss.emulab.net"
XMLRPC_PORT   = 3069
SERVER_PATH   = "/usr/testbed"
URI = f"https://{XMLRPC_SERVER}:{XMLRPC_PORT}{SERVER_PATH}"

RESPONSE_SUCCESS = 0

def do_method(method, params):
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    ctx.load_cert_chain(CERT_PATH, password=PEM_PWORD)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    server = xmlrpc_client.ServerProxy(URI, context=ctx)
    meth = getattr(server, "portal." + method)
    meth_args = [PACKAGE_VERSION, params]
    try:
        response = meth(*meth_args)
    except xmlrpc_client.Fault as e:
        logging.error("XMLRPC Fault: %s", e.faultString)
        return -1, None
    return response.get("code", -1), response

def start_experiment(experiment_name, project_name, profile_name):
    params = {
        "name": experiment_name,
        "proj": project_name,
        "profile": f"{project_name},{profile_name}"
    }
    logging.info("Starting experiment with parameters: %s", params)
    return do_method("startExperiment", params)

def get_experiment_status(project_name, experiment_name):
    params = {"experiment": f"{project_name},{experiment_name}"}
    return do_method("experimentStatus", params)

def get_experiment_manifests(project_name, experiment_name):
    params = {"experiment": f"{project_name},{experiment_name}"}
    return do_method("experimentManifests", params)

def wait_for_experiment_ready(experiment_name, project_name, max_retries=30, delay=20):
    logging.info("Waiting for experiment '%s' to become ready...", experiment_name)
    for _ in range(max_retries):
        time.sleep(delay)
        rval, response = get_experiment_status(project_name, experiment_name)
        status_output = response.get("output", "").lower() if response else ""
        logging.info("Experiment status: %s", status_output.strip())
        if "ready" in status_output:
            return True
    logging.error("Experiment '%s' did not become ready in time.", experiment_name)
    return False

def extract_node_ip(manifest_output):
    try:
        manifest_dict = xmltodict.parse(manifest_output)
        node = manifest_dict.get("rspec", {}).get("node")
        if isinstance(node, list):
            node = node[0]
        host = node.get("host")
        return host.get("@ipv4") if host else None
    except Exception as e:
        logging.error("XML parsing failed: %s", e)
        return None

# Simple SSH connection abstraction
class SSHConnection:
    def __init__(self, user, host, pem_path, timeout=60):
        self.user = user
        self.host = host
        self.pem_path = pem_path
        self.timeout = timeout
        self.base_cmd = [
            "ssh",
            "-vvv",
            "-o", "StrictHostKeyChecking=no",
            "-i", self.pem_path,
            f"{self.user}@{self.host}"
        ]
    
    def open(self):
        logging.info("Opening SSH connection to %s@%s", self.user, self.host)
        return self

    def command(self, cmd, timeout=None, expected_line=None):
        timeout = timeout if timeout is not None else self.timeout
        full_cmd = self.base_cmd + [cmd]
        logging.info("Running SSH command: %s", " ".join(full_cmd))
        result = subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            raise Exception(f"SSH command failed (exit code {result.returncode}): {result.stderr}")
        if expected_line and expected_line not in result.stdout:
            raise Exception(f"Expected line '{expected_line}' not found in output.")
        return result.stdout

    def copy_from(self, remote_path, local_path):
        scp_cmd = [
            "scp",
            "-o", "StrictHostKeyChecking=no",
            "-i", self.pem_path,
            f"{self.user}@{self.host}:{remote_path}",
            local_path
        ]
        logging.info("Running SCP command: %s", " ".join(scp_cmd))
        result = subprocess.run(scp_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception(f"SCP command failed (exit code {result.returncode}): {result.stderr}")
        return result.stdout

    def close(self, delay=0):
        if delay:
            time.sleep(delay)
        logging.info("Closing SSH connection to %s@%s", self.user, self.host)

def debug_print_pem(file_path, num_lines=2):
    try:
        with open(file_path, "r") as f:
            for i in range(num_lines):
                line = f.readline().rstrip()
                logging.info("PEM line %d: %s", i+1, line)
    except Exception as e:
        logging.error("Error reading PEM file: %s", e)

def main():
    project_name = os.environ.get("CLOUDLAB_PROJECT_NAME", "YourProject")
    profile_name = os.environ.get("CLOUDLAB_PROFILE_NAME", "default-profile")
    experiment_name = os.environ.get("EXPERIMENT_NAME", f"{profile_name}-experiment")
    logging.info("Using experiment name: %s", experiment_name)
    
    logging.info("Checking status for experiment '%s'...", experiment_name)
    rval, response = get_experiment_status(project_name, experiment_name)
    if rval == RESPONSE_SUCCESS:
        status_output = response.get("output", "").lower()
        if any(keyword in status_output for keyword in ["ready", "provisioning", "provisioned"]):
            logging.info("Experiment '%s' is already running: %s", experiment_name, status_output.strip())
        else:
            logging.info("Experiment '%s' exists but is not running: %s", experiment_name, status_output.strip())
            rval, response = start_experiment(experiment_name, project_name, profile_name)
            if rval != RESPONSE_SUCCESS:
                logging.error("Failed to start experiment: %s", response)
                sys.exit(1)
            if not wait_for_experiment_ready(experiment_name, project_name):
                sys.exit(1)
    else:
        logging.info("No existing experiment found with name '%s'. Starting a new experiment...", experiment_name)
        rval, response = start_experiment(experiment_name, project_name, profile_name)
        if rval != RESPONSE_SUCCESS:
            logging.error("Failed to start experiment: %s", response)
            sys.exit(1)
        if not wait_for_experiment_ready(experiment_name, project_name):
            sys.exit(1)
    
    rval, response = get_experiment_manifests(project_name, experiment_name)
    manifest_output = response.get("output", "")
    logging.info("Experiment manifest output:\n%s", manifest_output)
    
    node_ip = extract_node_ip(manifest_output)
    if node_ip:
        logging.info("Found deploy node IP: %s", node_ip)
    else:
        logging.error("Could not extract node IP from experiment manifests")
        sys.exit(1)
    
    # Debug: print first two lines of the PEM file.
    debug_print_pem(CERT_PATH, num_lines=2)
    
    try:
        ssh_conn = SSHConnection(LOGIN_ID, node_ip, CERT_PATH).open()
        hostname = ssh_conn.command("hostname", timeout=30)
        logging.info("Remote node hostname: %s", hostname.strip())
        ssh_conn.close(5)
    except Exception as e:
        logging.error("SSH command failed: %s", e)
        sys.exit(1)

if __name__ == "__main__":
    main()
