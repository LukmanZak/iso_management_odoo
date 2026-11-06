from . import models


def post_init_hook(env):
    """Load the ISO 14001:2015 catalog; never overwrite a user's ISO records."""
    env["iso.management.standard"].seed_catalog()
