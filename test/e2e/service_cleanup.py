# Copyright Amazon.com Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may
# not use this file except in compliance with the License. A copy of the
# License is located at
#
#	 http://aws.amazon.com/apache2.0/
#
# or in the "license" file accompanying this file. This file is distributed
# on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
# express or implied. See the License for the specific language governing
# permissions and limitations under the License.

"""Cleans up the resources created by service_bootstrap.py."""

import logging

from e2e import bootstrap_directory
from e2e.bootstrap_resources import BootstrapResources


def service_cleanup():
    logging.getLogger().setLevel(logging.INFO)

    try:
        resources = BootstrapResources.deserialize(bootstrap_directory)
    except Exception:
        logging.error("Could not load bootstrap resources — nothing to clean up")
        return

    resources.cleanup()
    logging.info("Cleanup complete.")


if __name__ == "__main__":
    service_cleanup()
