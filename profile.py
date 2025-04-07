import geni.portal as portal
import geni.rspec.pg as pg
import geni.rspec.igext as IG

pc = portal.Context()
pc.defineParameter(
    name="CLOUDLAB_SSH_PUB_KEY_B64",
    description="Base64-encoded SSH Public Key",
    typ=portal.ParameterType.STRING,
    default=""
)
params = pc.bindParameters()
request = pc.makeRequestRSpec()

tour = IG.Tour()
tour.Description(IG.Tour.TEXT, """
This profile spins up a node, installs Docker, Minikube, Skaffold, kubectl, and deploys the app automatically using skaffold.
""")
request.addTour(tour)

node = request.RawPC("deploy-node")
node.hardware_type = "d430"
node.disk_image = "urn:publicid:IDN+emulab.net+image+emulab-ops:UBUNTU22-64-STD"
node.routable_control_ip = True

bs = node.Blockstore("bs", "/mydata")
bs.size = "20GB"

username = "tg996676"
node.addService(pg.Execute(shell="/bin/sh", command=f"""
mkdir -p /local/logs
echo '[INFO] Writing startup script...' > /local/init.log

cat << EOF > /local/setup.sh
#!/bin/sh

LOG="/local/logs/ssh_debug.log"
mkdir -p /local/logs
echo "[START] SSH injection at $(date)" > $LOG

# Wait for user account
for i in $(seq 1 30); do
  if id {username} >/dev/null 2>&1; then
    echo "[INFO] Found user {username}" >> $LOG
    break
  fi
  echo "[WAIT] Waiting for user {username}..." >> $LOG
  sleep 2
done

if ! id {username} >/dev/null 2>&1; then
  echo "[ERROR] User {username} not found" >> $LOG
  exit 1
fi

mkdir -p /users/{username}/.ssh
echo '{params.CLOUDLAB_SSH_PUB_KEY}' > /users/{username}/.ssh/authorized_keys
chmod 600 /users/{username}/.ssh/authorized_keys
chown -R {username}:{username} /users/{username}/.ssh

echo "Resolved USER={username}" > /local/logs/who_was_user.txt
cat /users/{username}/.ssh/authorized_keys > /local/logs/authorized_keys.txt
echo "[DONE] SSH key injected at $(date)" >> $LOG
EOF

chmod +x /local/setup.sh
bash /local/setup.sh > /local/setup_output.log 2>&1
"""))




pc.printRequestRSpec(request)
