#!/bin/bash
# Compatibility wrapper – prefer running ./BuddyRemote directly
cd "$(dirname "$0")"
exec ./BuddyRemote "$@"
