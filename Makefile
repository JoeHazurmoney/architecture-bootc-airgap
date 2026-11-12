# Everything runs in the tools container (tools/Containerfile), never on the host Python.
# ENGINE=docker on workstations without podman. Linux build hosts and CI use podman or docker.
ENGINE      ?= podman
TOOLS_IMAGE ?= localhost/bootc-tools:latest
BASE_IMAGE  ?= quay.io/almalinuxorg/almalinux-bootc:10.2
VERSION     ?= dev
SOCKET      ?= /var/run/docker.sock

RUN = $(ENGINE) run --rm -v $(CURDIR):/work:z -w /work \
      -e ANSIBLE_CONFIG=/work/ansible/ansible.cfg $(TOOLS_IMAGE)

.PHONY: help tools lint render test images server-image stig stig-check stig-images check clean

help:
	@echo "make tools   - build the tools container"
	@echo "make lint    - yamllint + ansible-lint (production profile)"
	@echo "make render  - render Kickstarts/GRUB/DHCP for every inventory and validate them"
	@echo "make test    - molecule converge/idempotence/verify for bootc_pxe (needs $(SOCKET))"
	@echo "make images  - build server + workstation images on BASE_IMAGE (runs bootc container lint)"
	@echo "make stig    - regenerate the STIG tailoring, finding map and checklists from compliance/stig/"
	@echo "make stig-check - fail if the STIG outputs are stale or controls.yaml is invalid"
	@echo "make stig-images - build server, then server-stig on it"
	@echo "make check   - lint + render + stig-check + test"

tools:
	$(ENGINE) build -f tools/Containerfile -t $(TOOLS_IMAGE) .

lint: tools
	$(RUN) sh -c 'yamllint . && cd ansible && ansible-lint . ../lab/playbooks'

render: tools
	$(RUN) python3 tools/render_check.py

test: tools
	$(ENGINE) run --rm -v $(CURDIR):/work:z -v $(SOCKET):/var/run/docker.sock \
	  -w /work/ansible/roles/bootc_pxe -e ANSIBLE_CONFIG=/work/ansible/ansible.cfg \
	  $(TOOLS_IMAGE) molecule test

images: server-image
	$(ENGINE) build -f images/workstation/Containerfile --build-arg BASE_IMAGE=localhost/bootc/server:$(VERSION) \
	  --build-arg IMAGE_VERSION=$(VERSION) -t localhost/bootc/workstation:$(VERSION) images/

stig: tools
	$(RUN) python3 tools/stig_report.py generate

stig-check: tools
	$(RUN) python3 tools/stig_report.py check

server-image:
	$(ENGINE) build -f images/base/Containerfile --build-arg BASE_IMAGE=$(BASE_IMAGE) \
	  --build-arg IMAGE_VERSION=$(VERSION) -t localhost/bootc/server:$(VERSION) images/

stig-images: server-image
	$(ENGINE) build -f images/stig/Containerfile --build-arg BASE_IMAGE=localhost/bootc/server:$(VERSION) \
	  --build-arg STIG_PROFILE=stig --build-arg IMAGE_VERSION=$(VERSION) -t localhost/bootc/server-stig:$(VERSION) images/

check: lint render stig-check test

clean:
	rm -rf artifacts/
