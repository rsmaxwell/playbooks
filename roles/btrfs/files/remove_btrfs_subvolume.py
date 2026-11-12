#!/usr/bin/python3

import subprocess
import codecs
import sys
import json

def dump_command_result(command, result):
    print("--- [ command ]---------------")
    print(command, " --> returncode: ", result.returncode)
    print("--- [ stdout ]---------------")
    print(result.stdout.decode())
    print("--- [ stderr ]---------------")
    print(result.stderr.decode())
    print("-----------------------------")



def find_btrfs_executable():
    command = ["which", "btrfs"]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if (result.returncode == 1):
        print("The btrfs executable could not be found")
        return {
            "rc": 1
        }
    elif (result.returncode != 0):
        print("Unexpected error, returncode:", result.returncode)
        dump_command_result(command, result)
        return {
            "rc": 3
        }

    btrfs = result.stdout.decode().rstrip()

    return {
        "rc": 0,
        "btrfs": btrfs
    }



def btrfs_filesystem_df(btrfs, filesystem):
    command = [btrfs, "filesystem", "df", filesystem]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    if (result.returncode == 1):
        print("The btrfs filesystem '" + filesystem + "' not found")
        return {
            "rc": 0,
            "exists": False
        }
    elif (result.returncode != 0):
        print("Unexpected error, returncode:", result.returncode)
        dump_command_result(command, result)
        return {
            "rc": 3
        }

    path = result.stdout.decode().rstrip()
    print("The btrfs filesystem '" + filesystem + "' exists")

    return {
        "rc": 0,
        "exists": True,
        "path": path
    }



def btrfs_subvolume_show(btrfs, subvolume):
    command = [btrfs, "subvolume", "show", subvolume]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    rc = 0
    found = True

    if (result.returncode == 0):
        path = result.stdout.decode().rstrip()
        print("The btrfs subvolume '" + subvolume + "' already exists")
    elif (result.returncode == 1):
        print("The btrfs subvolume '" + subvolume + "' not found")
        found = False
    else:
        print("Unexpected error, returncode:", result.returncode)
        dump_command_result(command, result)
        rc = 3

    return {
        "rc": rc,
        "found": found
    }


def btrfs_test_quotas_enabled(btrfs, filesystem):
    command = [btrfs, "qgroup", "show", filesystem]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    enabled = True

    if (result.returncode == 0):
        print("Quotas are already enabled for btrfs filesystem '" + filesystem + "'")
    elif (result.returncode == 1):
        print("Quotas are not enabled for btrfs filesystem '" + filesystem + "'")
        enabled = False
    else:
        print("Unexpected error, returncode:", result.returncode)
        dump_command_result(command, result)
        return {
            "rc": 3
        }

    return {
        "rc": 0,
        "enabled": enabled
    }



def btrfs_quota_disable(btrfs, filesystem):
    command = [btrfs, "quota", "disable", filesystem]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if (result.returncode == 0):
        print("Quotas disabled for subvolume: '" + subvolume + "'")
    else:
        print("Quotas could not be disabled for subvolume: '" + subvolume + "'")
        dump_command_result(command, result)
        return {
            "rc": 3
        }

    return {
        "rc": 0
    }



def btrfs_subvolume_delete(btrfs, subvolume):
    args = [btrfs, "subvolume", "delete", subvolume]
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    if (result.returncode != 0):
        print("The btrfs subvolume '" + subvolume + "' could not be deleted")
        dump_command_result(command, result)
        return {
            "rc": 3
        }

    print("The btrfs subvolume '" + subvolume + "' deleted sucessfully")
    return {
        "rc": 0
    }







changed = False


if (len(sys.argv) < 3):
    print("syntax: initialise_btrfs_subvolume <filesystem> <subvolume>")
    sys.exit(2)

filesystem = sys.argv[1]
subvolume = sys.argv[2]
print("{ filesystem: '" + filesystem + "', subvolume: '" + subvolume + "' }")



result = find_btrfs_executable()
if (result["rc"] != 0):
    sys.exit(3)

btrfs = result["btrfs"]





result = btrfs_filesystem_df(btrfs, filesystem)
if (result["rc"] != 0):
    sys.exit(3)

if (result["exists"] == False):
    sys.exit(3)




result = btrfs_subvolume_show(btrfs, subvolume)
if (result["rc"] != 0):
    sys.exit(3)

if (result["found"] == False):
    sys.exit(0)





result = btrfs_test_quotas_enabled(btrfs, filesystem)
if (result["rc"] != 0):
    sys.exit(3)

quotas_are_enabled = result["enabled"]





if (quotas_are_enabled == True):
    result = btrfs_quota_disable(btrfs, filesystem)
    if (result["rc"] != 0):
        sys.exit(3)



result = btrfs_subvolume_delete(btrfs, subvolume)
if (result["rc"] != 0):
    sys.exit(3)

changed = True





if (changed):
    sys.exit(1)

sys.exit(0)