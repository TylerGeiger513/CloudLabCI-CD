#!/usr/bin/env python3
import os
import sys
import time
import logging
import re
import subprocess
import ssl
import xmlrpc.client as xmlrpc_client

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")

# Client package version for the API
PACKAGE_VERSION = 0.1

# Read CloudLab/Emulab credentials from environment variables.
try:
    LOGIN_ID  = os.environ['USER']
    PEM_PWORD = os.environ['PWORD']
    CERT_PATH = os.environ['CERT']
except KeyError:
    logging.error("Missing CloudLab credential environment variables (USER, PWORD, CERT)")
    sys.exit(1)

# XML-RPC server configuration for Emulab/CloudLab.
XMLRPC_SERVER = "boss.emulab.net"
XMLRPC_PORT   = 3069
SERVER_PATH   = "/usr/testbed"
URI           = "https://" + XMLRPC_SERVER + ":" + str(XMLRPC_PORT) + SERVER_PATH

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

    rval = response.get("code", -1)
    return rval, response

def start_experiment(experiment_name, project_name, profile_name):
    params = {
        "name": experiment_name,
        "proj": project_name,
        "profile": ','.join([project_name, profile_name])
    }
    logging.info("Starting experiment with parameters: %s", params)
    rval, response = do_method("startExperiment", params)
    return rval, response

def get_experiment_status(project_name, experiment_name):
    params = {
        "experiment": ','.join([project_name, experiment_name])
    }
    rval, response = do_method("experimentStatus", params)
    return rval, response

def get_experiment_manifests(project_name, experiment_name):
    params = {
        "experiment": ','.join([project_name, experiment_name])
    }
    rval, response = do_method("experimentManifests", params)
    return rval, response

def wait_for_experiment_ready(experiment_name, project_name, max_retries=30, delay=20):
    logging.info("Waiting for experiment '%s' to become ready...", experiment_name)
    for i in range(max_retries):
        time.sleep(delay)
        rval, response = get_experiment_status(project_name, experiment_name)
        status_output = response.get("output", "").lower()
        logging.info("Experiment status: %s", status_output.strip())
        if "ready" in status_output:
            logging.info("Experiment '%s' is ready.", experiment_name)
            return True
    logging.error("Experiment '%s' did not become ready in time.", experiment_name)
    return False

def main():
    # Retrieve project and profile names from environment variables
    project_name = os.environ.get("CLOUDLAB_PROJECT_NAME", "YourProject")
    profile_name = os.environ.get("CLOUDLAB_PROFILE_NAME", "default-profile")
    
    # Use a fixed experiment name (either provided or generated based on the profile)
    experiment_name = os.environ.get("EXPERIMENT_NAME", f"{profile_name}-experiment")
    logging.info("Using experiment name: %s", experiment_name)
    
    # Check if an experiment with this name is already running.
    logging.info("Checking status for experiment '%s'...", experiment_name)
    rval, response = get_experiment_status(project_name, experiment_name)
    if rval == RESPONSE_SUCCESS:
        status_output = response.get("output", "").lower()
        if any(keyword in status_output for keyword in ["ready", "provisioning", "provisioned"]):
            logging.info("Experiment '%s' is already running with status: %s", experiment_name, status_output.strip())
        else:
            logging.info("Experiment '%s' exists but is not in a running state: %s", experiment_name, status_output.strip())
            logging.info("Attempting to start experiment '%s'...", experiment_name)
            rval, response = start_experiment(experiment_name, project_name, profile_name)
            if rval != RESPONSE_SUCCESS:
                logging.error("Failed to start experiment: %s", response)
                sys.exit(1)
            if not wait_for_experiment_ready(experiment_name, project_name):
                sys.exit(1)
    else:
        # No existing experiment found; start a new one.
        logging.info("No existing experiment found with name '%s'. Starting a new experiment...", experiment_name)
        rval, response = start_experiment(experiment_name, project_name, profile_name)
        if rval != RESPONSE_SUCCESS:
            logging.error("Failed to start experiment: %s", response)
            sys.exit(1)
        if not wait_for_experiment_ready(experiment_name, project_name):
            sys.exit(1)
    
    # At this point, the experiment is running.
    # Retrieve experiment manifests to extract the deploy node's IP.
    rval, response = get_experiment_manifests(project_name, experiment_name)
    manifest_output = response.get("output", "")
    
    # Simplistic regex to find an IPv4 address in the manifest.
    logging.info("Experiment manifest output:\n%s", manifest_output)
    m = re.search(r'ipv4:\s*([\d\.]+)', manifest_output)
    if m:
        node_ip = m.group(1)
        logging.info("Found deploy node IP: %s", node_ip)
    else:
        logging.error("Could not extract node IP from experiment manifests")
        sys.exit(1)
    
    # Use SSH to connect to the deploy node and run 'hostname'.
    ssh_cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-i", CERT_PATH,
        f"{LOGIN_ID}@{node_ip}",
        "hostname"
    ]
    logging.info("Executing SSH command: %s", " ".join(ssh_cmd))
    try:
        result = subprocess.run(ssh_cmd, capture_output=True, text=True, check=True)
        hostname = result.stdout.strip()
        logging.info("Remote node hostname: %s", hostname)
    except subprocess.CalledProcessError as e:
        logging.error("SSH command failed: %s", e)
        sys.exit(1)

if __name__ == "__main__":
    main()
