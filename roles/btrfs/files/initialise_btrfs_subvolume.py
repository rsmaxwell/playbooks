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



def btrfs_quota_enable(btrfs, filesystem):
    command = [btrfs, "quota", "enable", filesystem]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if (result.returncode == 0):
        print("Quotas enabled for subvolume: '" + subvolume + "'")
    else:
        print("Quotas could not be enabled for subvolume: '" + subvolume + "'")
        dump_command_result(command, result)
        return {
            "rc": 3
        }

    return {
        "rc": 0
    }



def btrfs_subvolume_create(btrfs, subvolume):
    command = [btrfs, "subvolume", "create", subvolume]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if (result.returncode != 0):
        print("The btrfs subvolume '" + subvolume + "' could not be created")
        dump_command_result(command, result)
        return {
            "rc": 3
        }

    print("The btrfs subvolume '" + subvolume + "' created sucessfully")
    return {
        "rc": 0
    }


def btrfs_qgroup_show(btrfs, subvolume):
    command = [btrfs, "qgroup", "show", "-ref", "--raw", subvolume]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if (result.returncode != 0):
        print("Unexpected error, returncode:", result.returncode)
        dump_command_result(command, result)
        return {
            "rc": 3
        }
   
    path = result.stdout.decode().rstrip()
    print("The qgroups in the btrfs subvolume '" + subvolume + "' were displayed sucessfully")

    lines = [line for line in result.stdout.decode().splitlines() if line.strip()]

    if len(lines) < 3:
        print("Unexpected output from btrfs qgroup show")
        dump_command_result(command, result)
        return {
            "rc": 3
        }

    line = lines[-1]

    words = line.split()

    if len(words) < 5:
        print("Unexpected words in line")
        print("line: ", line)
        dump_command_result(command, result)
        return {
            "rc": 3
        }

    qgroupid = words[0]
    refer = words[1]
    excl = words[2]
    max_rfer = words[3]
    max_excl = words[4]
    path = words[5] if len(words) > 5 else None

    print(
        "{ qgroupid: '" + qgroupid +
        "', refer: '" + refer +
        "', excl: '" + excl +
        "', max_rfer: '" + max_rfer +
        "', max_excl: '" + max_excl +
        "', path: '" + str(path) + "' }"
)

    return {
        "rc": 0,
        "qgroupid": qgroupid,
        "refer": refer,
        "excl": excl,
        "max_rfer": max_rfer,
        "max_excl": max_excl
    }



def btrfs_qgroup_limit(btrfs, limit, qgroupid, subvolume):
    command = [btrfs, "qgroup", "limit", limit, qgroupid, subvolume]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if (result.returncode != 0):
        print("Could not set limits on subvolume quota group")
        dump_command_result(command, result)
        return {
            "rc": 3
        }

    print("Set limits on subvolume quota group was successful")
    return {
        "rc": 0
    }


changed = False


if (len(sys.argv) < 3):
    print("syntax: initialise_btrfs_subvolume <filesystem> <subvolume> <limit>")
    sys.exit(2)

filesystem = sys.argv[1]
subvolume = sys.argv[2]
limit = sys.argv[3]
print("{ filesystem: '" + filesystem + "', subvolume: '" + subvolume + "', limit: '" + limit + "' }")



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

subvolume_exists = result["found"]







if (subvolume_exists == False):
    result = btrfs_test_quotas_enabled(btrfs, filesystem)
    if (result["rc"] != 0):
        sys.exit(3)

    quotas_are_enabled = result["enabled"]





    if (quotas_are_enabled == False):
        result = btrfs_quota_enable(btrfs, filesystem)
        if (result["rc"] != 0):
            sys.exit(3)



    result = btrfs_subvolume_create(btrfs, subvolume)
    if (result["rc"] != 0):
        sys.exit(3)

    changed = True



result = btrfs_qgroup_show(btrfs, subvolume)
if (result["rc"] != 0):
    sys.exit(3)

qgroupid = result["qgroupid"]




if (result["max_rfer"] != limit):

    result = btrfs_qgroup_limit(btrfs, limit, qgroupid, subvolume)
    if (result["rc"] != 0):
        sys.exit(3)

    changed = True





if (changed):
    sys.exit(1)

sys.exit(0)