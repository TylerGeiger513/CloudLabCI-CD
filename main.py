#!/usr/bin/env python3
import logging
import mmap
import multiprocessing as mp
import powder.experiment as pexp
import random
import re
import string
import sys
import time

logging.basicConfig(
    level=logging.DEBUG,
    format="[%(asctime)s] %(name)s:%(levelname)s: %(message)s"
)


class OAINoS1Controlled:
    """Instantiates a Powder Experiment based on the Powder Profile `PROFILE_NAME`
    and interacts with the nodes in the experiment in order to setup, build, and
    test an OAI RAN network in a controlled RF environment. Logs for each step
    are collected from the nodes and stored in this directory.

    """

    # Powder Experiment credentials
    PROJECT_NAME = 'PowderProfiles'
    PROFILE_NAME = 'oai-nos1-wired'
    EXPERIMENT_NAME_PREFIX = 'oai-nos1-'

    def __init__(self, oai_commit_hash='v1.2.1', experiment_name=None):
        self.commit_hash = oai_commit_hash
        if experiment_name is not None:
            self.experiment_name = experiment_name
        else:
            self.experiment_name = self.EXPERIMENT_NAME_PREFIX + self._random_string()

    def run(self):
        self._start_powder_experiment()._setup_nodes()._build_nodes()

        nos1_up = False
        retry_count = 0
        while not nos1_up and retry_count < 10:
            logging.info('trying to establish noS1 network... attempt {}/10'.format(retry_count + 1))
            nos1_up = self._start_nos1_network()

        if nos1_up:
            logging.info('UE connected to eNB after {} attempt(s)'.format(retry_count + 1))
            self._run_ping_enb()
            self._stop_nos1_network()
        else:
            logging.info('Failed to setup noS1 network.')

        self._finish()

    def _random_string(self, strlen=7):
        characters = string.ascii_lowercase + string.digits
        return ''.join(random.choice(characters) for i in range(strlen))

    def _start_powder_experiment(self):
        self.exp = pexp.PowderExperiment(experiment_name=self.experiment_name,
                                         project_name=self.PROJECT_NAME,
                                         profile_name=self.PROFILE_NAME)

        exp_status = self.exp.start_and_wait()
        if exp_status != self.exp.EXPERIMENT_READY:
            logging.error('failed to start experiment')
            self.test_status = self.TEST_NOT_STARTED
            self._finish()

        return self

    def _setup_nodes(self):
        self.test_status = self.TEST_STARTED
        # Run setup in parallel
        enb_setup_proc = mp.Process(target=self._setup_enb)
        enb_setup_proc.daemon = True
        enb_setup_proc.start()

        ue_setup_proc = mp.Process(target=self._setup_ue)
        ue_setup_proc.daemon = True
        ue_setup_proc.start()

        enb_setup_proc.join()
        ue_setup_proc.join()

        setup_valid = self._parse_setup_logs()
        if not setup_valid:
            logging.error('setup for enb and/or ue failed, test aborted')
            logging.error('see setup logs for details')
            self._finish()

        return self

    def _parse_setup_logs(self):
        enb_setup_valid = self._find_bytes_in_file(bytestr=b'Host setup complete',
                                                   filename='setup_oai_enb.log')
        ue_setup_valid = self._find_bytes_in_file(bytestr=b'Host setup complete',
                                                  filename='setup_oai_ue.log')

        return enb_setup_valid and ue_setup_valid

    def _find_bytes_in_file(self, bytestr, filename):
        with open(filename, 'r+') as f:
            data = mmap.mmap(f.fileno(), 0)
            out = re.search(bytestr, data)
            if out:
                return True
            else:
                return False

    def _build_nodes(self):
        enb_build_proc = mp.Process(target=self._build_enb)
        enb_build_proc.daemon = True
        enb_build_proc.start()

        ue_build_proc = mp.Process(target=self._build_ue)
        ue_build_proc.daemon = True
        ue_build_proc.start()

        enb_build_proc.join()
        ue_build_proc.join()

        builds_valid = self._parse_build_logs()
        if not builds_valid:
            logging.error('build for enb and/or ue failed, test aborted')
            logging.error('see build logs for details')
            self.test_status = self.TEST_FAILED
            self._finish()
        else:
            return self

    def _parse_build_logs(self):
        enb_build_valid = self._find_bytes_in_file(bytestr=b'Bypassing the Tests',
                                                   filename='compile_oai_enb.log')
        ue_build_valid = self._find_bytes_in_file(bytestr=b'Bypassing the Tests',
                                                  filename='compile_oai_ue.log')

        return enb_build_valid and ue_build_valid

    def _setup_enb(self):
        logging.info('setting up enb')
        ssh_enb = self.exp.nodes['enb1'].ssh.open()
        ssh_enb.command('cd /local/repository')
        ssh_enb.command('stdbuf -o0 ./bin/setup.sh 2>&1 | stdbuf -o0 tee /tmp/setup_oai_enb.log',
                        expectedline='Host setup complete!', timeout=1800)
        ssh_enb.copy_from(remote_path='/tmp/setup_oai_enb.log', local_path='./setup_oai_enb.log')
        ssh_enb.command('cp /local/repository/etc/enb.conf /local/enb.conf')
        ssh_enb.command('VLANIF=$(ifconfig | grep vlan | cut -d ":" -f1)')
        ssh_enb.command('VLANIP=$(ip addr list "$VLANIF" | grep "inet " | cut -d" " -f6|cut -d"/" -f1)')
        ssh_enb.command('EPCIP=$VLANIP')
        ssh_enb.command('sed -i -e "s/CI_MME_IP_ADDR/$EPCIP/" /local/enb.conf')
        ssh_enb.command('sed -i -e "s/CI_ENB_IP_ADDR/$VLANIP/" /local/enb.conf')
        ssh_enb.command('sed -i -e "s/eth0/$VLANIF/" /local/enb.conf')
        ssh_enb.close(5)

    def _build_enb(self):
        logging.info('building enb')
        ssh_enb = self.exp.nodes['enb1'].ssh.open()
        ssh_enb.command('cd /local/openairinterface5g/')
        ssh_enb.command('git checkout {}'.format(self.commit_hash))
        ssh_enb.command('source oaienv')
        ssh_enb.command('cd /local/openairinterface5g/cmake_targets/')
        ssh_enb.command('stdbuf -o0 ./build_oai -I -w USRP --eNB 2>&1 | stdbuf -o0 tee /tmp/compile_oai_enb.log',
                        'Bypassing the Tests|build have failed', 1800)
        ssh_enb.copy_from(remote_path='/tmp/compile_oai_enb.log', local_path='./compile_oai_enb.log')
        ssh_enb.close(5)
        logging.info('finished building enb')

    def _setup_ue(self):
        logging.info('setting up ue')
        ssh_ue = self.exp.nodes['rue1'].ssh.open()
        ssh_ue.command('cd /local/repository')
        ssh_ue.command('stdbuf -o0 ./bin/setup.sh 2>&1 | stdbuf -o0 tee /tmp/setup_oai_ue.log',
                       expectedline='Host setup complete!', timeout=1800)
        ssh_ue.copy_from(remote_path='/tmp/setup_oai_ue.log', local_path='./setup_oai_ue.log')
        ssh_ue.close(5)

    def _build_ue(self):
        logging.info('building ue')
        ssh_ue = self.exp.nodes['rue1'].ssh.open()
        ssh_ue.command('cd /local/openairinterface5g/')
        ssh_ue.command('git checkout {}'.format(self.commit_hash))
        ssh_ue.command('source oaienv')
        ssh_ue.command('cd /local/openairinterface5g/cmake_targets/')
        ssh_ue.command('stdbuf -o0 ./build_oai -I -w USRP --UE 2>&1 | stdbuf -o0 tee /tmp/compile_oai_ue.log',
                       'Bypassing the Tests|build have failed', 1800)
        ssh_ue.copy_from(remote_path='/tmp/compile_oai_ue.log', local_path='./compile_oai_ue.log')
        ssh_ue.close(5)
        logging.info('finished building ue')

    def _start_nos1_network(self):
        self._enb_exec_proc = mp.Process(target=self._start_enb)
        self._enb_exec_proc.daemon = True
        self._enb_exec_proc.start()

        time.sleep(20)

        self._ue_exec_proc = mp.Process(target=self._start_ue)
        self._ue_exec_proc.daemon = True
        self._ue_exec_proc.start()

        time.sleep(20)
        nos1_up = self._check_nos1_network()
        if not nos1_up:
            logging.error('UE failed to connect to eNB')
            logging.error('killing eNB and UE processes')
            self._kill_nos1_network()

        return nos1_up

    def _check_nos1_network(self):
        ssh_ue = self.exp.nodes['rue1'].ssh.open()
        ssh_ue.command('cd /local/repository')
        ssh_ue.command('ifconfig')
        if_exists = re.search('oaitun_ue1', str(ssh_ue.ssh.before))
        ip_exists = re.search('10.0.1.2', str(ssh_ue.ssh.before))
        ssh_ue.close(5)
        if if_exists and ip_exists:
            return True
        else:
            return False

    def _kill_nos1_network(self):
        self._ue_exec_proc.kill()
        self._enb_exec_proc.kill()

    def _run_ping_enb(self):
        ssh_ue = self.exp.nodes['rue1'].ssh.open()
        ssh_ue.command('stdbuf -o0 ping -c 10 10.0.1.1 2>&1 | stdbuf -o0 tee /tmp/ue_ping_enb.log',
                       expectedline='packets transmitted', timeout=120)
        ssh_ue.copy_from(remote_path='/tmp/ue_ping_enb.log', local_path='./ue_ping_enb.log')
        ssh_ue.close(5)

    def _start_enb(self):
        ssh_enb = self.exp.nodes['enb1'].ssh.open()
        ssh_enb.command('cd /local/openairinterface5g/')
        ssh_enb.command('source oaienv')
        ssh_enb.command('cd /local/openairinterface5g/cmake_targets/')
        ssh_enb.command('sudo -E ./lte_build_oai/build/lte-softmodem -O /local/enb.conf --nokrnmod 1 --noS1 --eNBs.[0].rrc_inactivity_threshold 0 2>&1 | tee /tmp/enb.log',
                        expectedline='unexpectedline', timeout=1800)
        ssh_enb.copy_from(remote_path='/tmp/enb.log', local_path='./enb.log')

    def _start_ue(self):
        ssh_ue = self.exp.nodes['rue1'].ssh.open()
        ssh_ue.command('cd /local/openairinterface5g/cmake_targets/lte_build_oai/build/')
        ssh_ue.command('sudo ./lte-uesoftmodem -C 2685000000 -r 25 --ue-rxgain 120 --ue-txgain 20 --ue-max-power 0 --ue-scan-carrier --nokrnmod 1 --noS1 2>&1 | tee /tmp/ue.log',
                       expectedline='unexpectedline', timeout=1800)
        ssh_ue.copy_from(remote_path='/tmp/ue.log', local_path='./ue.log')

    def _finish(self):
        import ipdb; ipdb.set_trace()
        if self.exp.status not in [self.exp.EXPERIMENT_NULL, self.exp.EXPERIMENT_NOT_STARTED]:
            self.exp.terminate()

        sys.exit(self.test_status)


if __name__ == '__main__':
    oai_nos1_controlled = OAINoS1Controlled(oai_commit_hash='v1.2.1')
    oai_nos1_controlled.run()
