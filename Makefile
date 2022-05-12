# python 3.6 is used, for the time being, in order to ensure compatibility
install:
	{ python3.6 -m venv venv || python3 -m venv venv || \
	py -3.6 -m venv venv || py -3 -m venv venv ; } && \
	{ . venv/bin/activate || venv/Scripts/activate.bat ; } && \
	python3 -m pip install --upgrade pip && \
	python3 -m pip install\
	 -r requirements.txt\
	 -e . && \
	mypy --install-types --non-interactive ; \
	echo "Success!"

# Install dependencies locally where available
editable:
	{ . venv/bin/activate || venv/Scripts/activate.bat ; } && \
	daves-dev-tools install-editable --upgrade-strategy eager && \
	make requirements && \
	echo "Success!"

# Cleanup unused packages, and Git-ignored files (such as build files)
clean:
	{ . venv/bin/activate || venv/Scripts/activate.bat ; } && \
	daves-dev-tools uninstall-all\
	 -e .\
     -e pyproject.toml\
     -e tox.ini\
     -e requirements.txt && \
	daves-dev-tools clean && \
	echo "Success!"

# Distribute to PYPI
distribute:
	{ . venv/bin/activate || venv/Scripts/activate.bat ; } && \
	daves-dev-tools distribute --skip-existing && \
	echo "Success!"

# Upgrade
upgrade:
	{ . venv/bin/activate || venv/Scripts/activate.bat ; } && \
	daves-dev-tools requirements freeze\
	 -nv '*' . pyproject.toml tox.ini \
	 > .unversioned_requirements.txt && \
	python3 -m pip install --upgrade --upgrade-strategy eager\
	 -r .unversioned_requirements.txt -e . && \
	rm .unversioned_requirements.txt && \
	make requirements

# Update requirement version #'s to match the current environment
requirements:
	{ . venv/bin/activate || venv/Scripts/activate.bat ; } && \
	daves-dev-tools requirements update\
	 -aen all\
	 setup.cfg pyproject.toml tox.ini && \
	daves-dev-tools requirements freeze\
	 -nv setuptools -nv filelock -nv platformdirs\
	 . pyproject.toml tox.ini daves-dev-tools\
	 > requirements.txt && \
	echo "Success!"

# Download specification schemas
schemas:
	{ . venv/bin/activate || venv/Scripts/activate.bat ; } && \
	python3 scripts/download_schemas.py && \
	echo "Success!"

# Rebuild the data model (to maintain consistency when/if changes are made
# which affect formatting)
remodel:
	{ . venv/bin/activate || venv/Scripts/activate.bat ; } && \
	python3 scripts/remodel.py && \
	echo "Success!"

# Run all tests
test:
	{ venv/Scripts/activate.bat || . venv/bin/activate; } && tox -r -p
