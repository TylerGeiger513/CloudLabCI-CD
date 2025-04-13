#!/usr/bin/env python3
import logging
import mmap
import random
import re
import string
import sys
import time
import os
import multiprocessing as mp

sys.path.append(os.path.join(os.path.dirname(__file__), 'powder'))

import powder.experiment as pexp

logging.basicConfig(
    level=logging.DEBUG, # Keep DEBUG level to see detailed logs
    format="[%(asctime)s] %(levelname)s:%(name)s:%(message)s", # Use %(levelname)s and %(name)s
    datefmt='%Y-%m-%d %H:%M:%S' # Added date format consistent with previous logs
)


class OAINoS1Controlled:
    """Instantiates a Powder experiment based on the Powder profile `PROFILE_NAME`
    and interacts with the nodes in the experiment. Currently focuses on 'deploy-node'.
    """

    # Powder experiment credentials
    PROJECT_NAME = os.environ.get('PROJECT_NAME', 'PowderProfiles')
    # Ensure this profile actually contains 'deploy-node' as intended
    PROFILE_NAME = os.environ.get('PROFILE_NAME', 'oai-nos1-wired') 
    EXPERIMENT_NAME_PREFIX = 'exp-'

    TEST_SUCCEEDED   = 0  # all steps succeeded
    TEST_FAILED      = 1  # one of the steps failed
    TEST_NOT_STARTED = 2  # could not instantiate an experiment to run the test on

    def __init__(self, oai_commit_hash='v1.2.1', experiment_name=None):
        self.commit_hash = oai_commit_hash
        if experiment_name is not None:
            self.experiment_name = experiment_name
        else:
            self.experiment_name = self.EXPERIMENT_NAME_PREFIX + self._random_string()
        
        # Placeholder for processes if needed later
        self._enb_exec_proc = None
        self._ue_exec_proc = None

    def run(self):
        """Main execution flow."""
        if not self._start_powder_experiment():
            self._finish(self.TEST_NOT_STARTED)
        
        logging.info("Experiment started successfully. Proceeding to node setup...")

        # --- Modified Flow: Only setup deploy-node for now ---
        if not self._setup_deploy_node():
             self._finish(self.TEST_FAILED)
        
        logging.info("Deploy node setup seems successful.")
        # --- End Modified Flow ---

        # --- Commented out multi-node steps ---
        # if not self._setup_nodes():
        #     self._finish(self.TEST_FAILED)

        # if not self._build_nodes():
        #     self._finish(self.TEST_FAILED)

        # if not self._start_nos1_network():
        #     self._finish(self.TEST_FAILED)

        # if not self._run_ping_test():
        #     self._finish(self.TEST_FAILED)
        # else:
        #     self._finish(self.TEST_SUCCEEDED)
        # --- End Commented out multi-node steps ---

        # For now, just succeed if deploy-node setup is okay
        self._finish(self.TEST_SUCCEEDED)


    def _random_string(self, strlen=7):
        characters = string.ascii_lowercase + string.digits
        return ''.join(random.choice(characters) for i in range(strlen))

    def _start_powder_experiment(self):
        logging.info('Instantiating Powder experiment...')
        # --- Add logging for profile name ---
        logging.info(f"Using Project: {self.PROJECT_NAME}, Profile: {self.PROFILE_NAME}")
        # --- End log line ---
        self.exp = pexp.PowderExperiment(experiment_name=self.experiment_name,
                                         project_name=self.PROJECT_NAME,
                                         profile_name=self.PROFILE_NAME)

        exp_status = self.exp.start_and_wait()
        if exp_status != self.exp.EXPERIMENT_READY:
            logging.error('Failed to start experiment.')
            # Attempt to terminate if experiment exists but isn't ready
            if hasattr(self, 'exp') and self.exp.status != self.exp.EXPERIMENT_NULL:
                 logging.info("Attempting to terminate failed/stuck experiment...")
                 self.exp.terminate()
            return False
        # Check if the expected node exists after experiment is ready
        elif 'deploy-node' not in self.exp.nodes:
             logging.error(f"Experiment is READY, but required 'deploy-node' was not found in manifests. Nodes found: {list(self.exp.nodes.keys())}")
             self.exp.terminate() # Terminate as the required node is missing
             return False
        else:
            logging.info(f"Experiment READY. Found nodes: {list(self.exp.nodes.keys())}")
            return True

    # --- New method for deploy-node setup ---
        # --- New method for deploy-node setup ---
    def _setup_deploy_node(self):
        """Sets up the deploy-node, waiting for the repository clone to complete."""
        logging.info('Setting up deploy-node...')
        log_filename = 'setup_deploy_node.log'
        success_marker = b'Deploy node setup complete!'
        repo_dir = "/local/repository"
        max_wait_time = 300 # Max seconds to wait for repo
        wait_interval = 10  # Seconds between checks

        try:
            ssh_deploy = self.exp.nodes['deploy-node'].ssh.open()

            # --- Wait loop for repository directory ---
            logging.info(f"Waiting for repository directory '{repo_dir}' to exist...")
            start_time = time.time()
            repo_exists = False
            while time.time() - start_time < max_wait_time:
                # Use a simple command to check if the directory exists
                check_cmd = f"test -d {repo_dir} && echo EXISTS"
                try:
                    # Use a short timeout for the check
                    check_output = ssh_deploy.command(check_cmd, expectedline="EXISTS", timeout=15) 
                    logging.info(f"Repository directory '{repo_dir}' found.")
                    repo_exists = True
                    break # Exit the loop if directory found
                except (TimeoutError, ConnectionAbortedError):
                    # Expected if the directory doesn't exist yet or command fails
                    logging.info(f"Directory '{repo_dir}' not found yet, waiting {wait_interval}s...")
                    time.sleep(wait_interval)
                except Exception as check_e:
                     logging.error(f"Error checking for directory '{repo_dir}': {check_e}")
                     # Break the loop on unexpected errors during check
                     break 

            if not repo_exists:
                logging.error(f"Repository directory '{repo_dir}' did not appear within {max_wait_time} seconds.")
                ssh_deploy.close()
                return False
            # --- End wait loop ---

            # --- Proceed with original command chain ---
            cmd = (
                f"cd {repo_dir} && " # Use variable
                "echo '--- Checking repository ---' && "
                "ls -la && "
                "echo '--- Running hostname ---' && "
                "hostname && "
                "echo '--- Running hostname -f ---' && "
                "hostname -f && "
                f"echo '{success_marker.decode()}'"
            )
            full_cmd = f"stdbuf -o0 {cmd} 2>&1 | stdbuf -o0 tee /tmp/{log_filename}"

            # Execute command, expecting the success marker (restore original timeout)
            output = ssh_deploy.command(full_cmd, expectedline=success_marker.decode(), timeout=120) 
            logging.info(f"--- Remote Command Output (deploy-node) ---\n{output.strip()}")
            # --- End original command chain ---

            # Copy log back and close
            ssh_deploy.copy_from(remote_path=f'/tmp/{log_filename}', local_path=f'./{log_filename}')
            ssh_deploy.close(5)

            # Check log file
            if self._find_bytes_in_file(bytestr=success_marker, filename=log_filename):
                logging.info('deploy-node setup complete.')
                return True
            else:
                logging.error(f'deploy-node setup failed: Success marker not found in log file. Check {log_filename}.')
                return False

        except KeyError:
            logging.error("Failed to setup deploy-node: Node 'deploy-node' not found in experiment nodes.")
            return False
        except Exception as e:
            logging.error(f"An error occurred during deploy-node setup: {e}", exc_info=True)
            # Attempt to copy log file even if command failed before completion
            try:
                if 'ssh_deploy' in locals() and ssh_deploy.ssh and not ssh_deploy.ssh.closed:
                     ssh_deploy.copy_from(remote_path=f'/tmp/{log_filename}', local_path=f'./{log_filename}')
                     ssh_deploy.close(5)
                # Removed the extra copy attempt block for simplicity, main one should suffice
            except Exception as copy_e:
                 logging.error(f"Could not retrieve log file '{log_filename}' after setup error: {copy_e}")
            return False
                
        except KeyError:
            logging.error("Failed to setup deploy-node: Node 'deploy-node' not found in experiment nodes.")
            return False
        except Exception as e:
            logging.error(f"An error occurred during deploy-node setup: {e}", exc_info=True)
            # Attempt to copy log file even if command failed before completion
            try:
                # Ensure ssh_deploy exists before trying to use it
                if 'ssh_deploy' in locals() and ssh_deploy.ssh and not ssh_deploy.ssh.closed:
                     ssh_deploy.copy_from(remote_path=f'/tmp/{log_filename}', local_path=f'./{log_filename}')
                     ssh_deploy.close(5)
                else:
                     # If connection failed early, try getting a new handle just for copying
                     ssh_conn_for_copy = self.exp.nodes['deploy-node'].ssh
                     ssh_conn_for_copy.copy_from(remote_path=f'/tmp/{log_filename}', local_path=f'./{log_filename}')
                     # No need to close if we didn't open it here
            except Exception as copy_e:
                 logging.error(f"Could not retrieve log file '{log_filename}' after setup error: {copy_e}")
            return False
    # --- End new method ---
    # --- End new method ---


    # --- Commented out multi-node setup ---
    # def _setup_nodes(self):
    #     # Run setup in parallel
    #     enb_setup_proc = mp.Process(target=self._setup_enb)
    #     enb_setup_proc.daemon = True
    #     enb_setup_proc.start()

    #     ue_setup_proc = mp.Process(target=self._setup_ue)
    #     ue_setup_proc.daemon = True
    #     ue_setup_proc.start()

    #     enb_setup_proc.join()
    #     ue_setup_proc.join()

    #     setup_valid = self._parse_setup_logs()
    #     if not setup_valid:
    #         logging.info('Setup for enb1 and/or rue1 failed, test aborted.')
    #         logging.info('See ./ of logs for details')
    #         return False
    #     else:
    #         return True

    # def _setup_enb(self):
    #     # ... (code for enb1) ...
    #     pass

    # def _setup_ue(self):
    #     # ... (code for rue1) ...
    #     pass

    # def _parse_setup_logs(self):
    #     # ... (code to parse enb1 and rue1 logs) ...
    #     pass # Return True for now if only using deploy-node
    # --- End commented out multi-node setup ---


    def _find_bytes_in_file(self, bytestr, filename):
        """Checks if a byte string exists in a given file."""
        try:
            with open(filename, 'rb') as f: # Open in binary mode 'rb'
                # Use memory mapping for potentially large files
                with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                    if mm.find(bytestr) != -1:
                        return True
                    else:
                        return False
        except FileNotFoundError:
            logging.error(f"Log file '{filename}' not found for parsing.")
            return False
        except ValueError:
             logging.error(f"Log file '{filename}' is empty or cannot be mapped.")
             # Handle empty file case - does it mean success or failure? Assume failure.
             return False
        except Exception as e:
            logging.error(f"Error reading or mapping file '{filename}': {e}")
            return False


    # --- Commented out build, start, test, and kill methods ---
    # def _build_nodes(self):
    #     # ...
    #     pass

    # def _build_enb(self):
    #     # ...
    #     pass

    # def _build_ue(self):
    #     # ...
    #     pass

    # def _parse_build_logs(self):
    #     # ...
    #     pass

    # def _start_nos1_network(self):
    #     # ...
    #     pass

    # def _start_enb(self):
    #     # ...
    #     pass

    # def _start_ue(self):
    #     # ...
    #     pass

    # def _check_nos1_network(self):
    #     # ...
    #     pass

    # def _kill_nos1_network(self):
    #     logging.info('Killing any potential eNB and UE processes...')
    #     if self._ue_exec_proc and self._ue_exec_proc.is_alive():
    #         self._ue_exec_proc.terminate()
    #     if self._enb_exec_proc and self._enb_exec_proc.is_alive():
    #         self._enb_exec_proc.terminate()

    # def _run_ping_test(self):
    #     # ...
    #     pass

    # def _run_ping_enb(self):
    #     # ...
    #     pass

    # def _parse_ping_log(self):
    #     # ...
    #     pass
    # --- End commented out methods ---


    def _finish(self, test_status):
        """Cleans up the experiment and exits."""
        # --- Ensure kill is called if processes might exist ---
        # self._kill_nos1_network() # Keep commented unless needed for deploy-node cleanup

        if hasattr(self, 'exp') and self.exp.status not in [self.exp.EXPERIMENT_NULL, self.exp.EXPERIMENT_NOT_STARTED]:
            logging.info("Terminating experiment...")
            self.exp.terminate()
        else:
             logging.info("No active experiment found to terminate.")

        if test_status == self.TEST_NOT_STARTED:
            logging.info('The experiment could not be started or the required node was missing.')
            sys.exit(test_status) # Exit with code 2
        elif test_status == self.TEST_FAILED:
            logging.info('The test failed during deploy-node setup.')
            sys.exit(test_status) # Exit with code 1
        elif test_status == self.TEST_SUCCEEDED:
            logging.info('The test focused on deploy-node succeeded.')
            sys.exit(test_status) # Exit with code 0
        else:
             logging.error(f"Unknown test status: {test_status}")
             sys.exit(99) # Exit with a distinct code


if __name__ == '__main__':
    # You might want to adjust the commit hash or make it irrelevant if not building OAI
    oai_nos1_controlled = OAINoS1Controlled(oai_commit_hash='v1.2.1') 
    oai_nos1_controlled.run()