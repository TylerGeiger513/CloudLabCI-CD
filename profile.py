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
echo '[INFO] Script started' > /local/logs/ssh_debug.log

# Wait for user to exist (max 60s)
for i in $(seq 1 30); do
  if id {username} >/dev/null 2>&1; then
    echo '[INFO] User {username} exists' >> /local/logs/ssh_debug.log
    break
  fi
  echo '[WAIT] Waiting for user {username}...' >> /local/logs/ssh_debug.log
  sleep 2
done

if ! id {username} >/dev/null 2>&1; then
  echo '[ERROR] User {username} not found after waiting.' >> /local/logs/ssh_debug.log
  exit 1
fi

mkdir -p /users/{username}/.ssh
echo '{params.CLOUDLAB_SSH_PUB_KEY}' > /users/{username}/.ssh/authorized_keys
chmod 600 /users/{username}/.ssh/authorized_keys
chown -R {username}:{username} /users/{username}/.ssh

echo '[SUCCESS] SSH key injected for {username}' >> /local/logs/ssh_debug.log
echo 'Resolved USER={username}' > /local/logs/who_was_user.txt
cat /users/{username}/.ssh/authorized_keys > /local/logs/authorized_keys.txt
"""))




pc.printRequestRSpec(request)
