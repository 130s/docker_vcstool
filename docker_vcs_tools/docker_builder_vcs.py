#! /usr/bin/env python3

# Copyright (C) 2021 Kinu Garage
# Licensed under Apache 2

import argparse
import datetime
from distutils.dir_util import copy_tree
import docker
from docker import APIClient
from io import BytesIO
import logging
import os
import sh
import shutil
import subprocess
import time

DESC_DBUILDER = """'docker build' command with 3 additional features.
                    1) clone arbitrary set of repos utilizing "vcstool",
                    2) automatically resolve dependency of the software (using "rosdep install", then
                    3) build and install (only catkin_tools is supported as of 2021/02).
                    The software to be cloned and built have to be Catkin/Colcon packages."""
MSG_ENTRYPT_NO_SUBST = "As of 2021/02 entrypoint is statically embedded in a Docker image as resolving entrypoint seems not easy."


class DockerBuilderVCS():
    """
    @summary See DESC_DBUILDER variable.
    """
    DEfAULT_DOCKER_IMG = "ubuntu:focal"
    DEfAULT_DOCKERFILE = "Dockerfile"

    def __init__(self):
        """
        """
        try:
            self._docker_client = docker.from_env()
        except (docker.errors.APIError, docker.errors.TLSParameterError) as e:
            logging.error(str(e))
            exit(1)
        pass

    def docker_login():
        try:
            # When pushing to cloud, log in to docker registry.
            if self._push_cloud:
               self._docker_client.login(
                   username=docker_account, password=docker_pw, registry=docker_registry)
        except (APIError, TLSParameterError) as e:
            logging.error(str(e))
            exit(1)

    def init(self, args):
        loglevel = logging.INFO
        log_path_file = ''  # TODO Make this passable
        if args.debug:
            loglevel = logging.DEBUG
        if args.log_file:
            log_path_file = '/tmp/dockerbuilder.log'
        logging.basicConfig(filename=log_path_file, level=loglevel)

        # Required args
        self._dockerfile_name = args.dockerfile

        self._push_cloud = args.push_cloud
        self._temp_workdir_host = args.workspace_on_host
        self._workspace_in_container = args.workspace_in_container
#        self._docker_account = args.docker_account
#        self._docker_pw = args.docker_pw
#        self._docker_registry = args.docker_registry
#        logging.debug("These are what's passed: docker_registry: {}".format(docker_registry))
#        if not (docker_registry):
#            logging.error("Missing Docker auth info. Exiting.\n These are what's passed: docker_registry: {}".format(docker_registry))
#            exit(1)

        #self.docker_login()

        # Set all other user inputs as a member variable.
        self._user_args = args

        # TODO Also move this portion to main to make API backward comp.
        # TODO Whether to include Docker API here is debatable.

    def _docker_build_exec_api(self, path_dockerfile, baseimg, path_repos, outimg="", rm_intermediate=True, entrypt_bin="", tmpwork_dir="/tmp", debug=False):
        """
        @brief Execute docker Python API via its lower-level API.
        """
        dockerfile = os.path.basename(path_dockerfile)
        dck_api = APIClient()

        fobj = BytesIO(dockerfile.encode('utf-8'))
        _resp_docker_build = [line for line in dck_api.build(
            buildargs={"BASE_DIMG": baseimg,
                       "ENTRY_POINT": entrypt_bin,
                       "PATH_REPOS": os.path.basename(path_repos),
                       "WS_IN_CONTAINER": self._workspace_in_container},
            dockerfile=dockerfile,
            fileobj=fobj,
            path=tmpwork_dir,
            quiet=debug,
            rm=rm_intermediate,
            tag=outimg
        )]
        return _resp_docker_build

    def _docker_build_exec_noapi(self, path_dockerfile, baseimg, path_repos, outimg="", rm_intermediate=True, entrypt_bin="", tmpwork_dir="/tmp", debug=False):
        """
        @deprecated: Not planned to be maintained. Use docker_build instead. This uses docker-py's method that misses some capability.
        @brief Execute docker Python API via its lower-level API.
        """
        img, _log = self._docker_client.images.build(
            dockerfile=os.path.basename(path_dockerfile),
            buildargs={"BASE_DIMG": baseimg,
                       "ENTRY_POINT": entrypt_bin,
                       "PATH_REPOS": os.path.basename(path_repos),
                       "WS_IN_CONTAINER": self._workspace_in_container},
            #path=tmpwork_dir,
            path=".",
            quiet=debug,
            rm=True,
            tag=outimg
        )
        return _log


    def _docker_run(self, dimage, cmd, envvars=None):
        """
        @param cmd: A string of command that is passed to `bash -c`.
        @type envvars: Dict
        @return A container object (https://docker-py.readthedocs.io/en/stable/containers.html#docker.models.containers.Container).
        """
        try:
            container = self._docker_client.containers.run(
                image=dimage,
                command=["bash", "-c", '{}'.format(cmd)],
                stream=True,
                environment=envvars,
                privileged=True
            )
        except docker.errors.ContainerError as e:
            logging.error("'docker run' failed: {}".format(str(e)))
            self.docker_readlog(e.stderr)
            raise e
        return container

    def copy(self, tmp_dir, list_files_src):
        """
        @summary: If the some files (dockerfile, path_repos) that 'docker build' uses are not under current dir,
            1. copy them in the temp folder on the host.
            2. CD into the temp folder so that 'docker build' run in that context.
        @param list_files_src: Path to a folder or file to be copied. 
        """
        if not os.path.isdir(tmp_dir):
            os.makedirs(tmp_dir)
        for path in list_files_src:
            logging.debug("File to be copied: '{}'".format(path))
            if os.path.isdir(path):
                copy_tree(os.path.abspath(path), os.path.join(tmp_dir, path))
            else:
                shutil.copy2(path, tmp_dir)
        logging.info("Files are copied into a temp dir: '{}'".format(os.listdir(tmp_dir)))
        return tmp_dir

    def docker_build(
            self,
            path_dockerfile, baseimg, path_repos="", outimg="", rm_intermediate=True, entrypt_bin="entry_point.bash", debug=False):
        """
        @brief Run 'docker build' using 'lower API version' https://docker-py.readthedocs.io/en/stable/api.html#module-docker.api.build.
            See also  https://github.com/docker/docker-py/issues/1400#issuecomment-273682010 for why lower API.
        @param entrypt_bin: Not implemented yet. Needs implemented to inject entrypoint in the built Docker img.
        """
        # Some verification for args.
        if not path_dockerfile:
            #raise ValueError("Missing value for '{}'".format(path_dockerfile))
            path_dockerfile = "./{}".format(DockerBuilderVCS.DEfAULT_DOCKERFILE)  # TODO if docker py sets default val then this won't be needed.
        if not outimg:
            outimg = baseimg + "_out"  # TODO make this customizable

        if entrypt_bin:
            logging.warning(MSG_ENTRYPT_NO_SUBST)

        try:
            _log = self._docker_build_exec_noapi(
                path_dockerfile, baseimg, path_repos, rm_intermediate=False, tmpwork_dir=tmp_dir, debug=debug)

        except docker.errors.BuildError as e:
            logging.error("'docker build' failed: {}".format(str(e)))
            _log = e.build_log
            raise e
        except Exception as e:
            logging.error("'docker build' failed: {}".format(str(e)))
            raise e
        finally:
            for line in _log:
                if 'stream' in line:
                    logging.error(line['stream'].strip())

        
    def check_prerequisite(self):
#        if not shutil.which("aws"):
#            raise RuntimeError("awscli not found to be installed. Exiting.")
        pass

    def docker_readlog(self, logobj):
        """
        @summary Tentative method to read logs returned from some Docker Py API methods that return JSON w/o line break.
        """
        for line in logobj:
            if 'stream' in line:
                # TODO Not necessarilly logging.error
                logging.error(line['stream'].strip())

    def docker_build_from_mount(self, docker_img, path_volume, debug=False):
        """
        @summary Build source that is in mounted volume if anything.
           Docker container will be started with the volume(s) to be mounted. Then build.
        @type paths_volume: [str]
        """
        _TMP_WS_DIR = "/workspace"
        _TMP_WS_MOUNTED_DIR = os.path.join(_TMP_WS_DIR, "src/mounted") 
        envvars = "-v {}:{}".format(path_volume, _TMP_WS_SRC_DIR)
        cmd = "cd {} && colcon build".format(_TMP_WS_DIR)
        container = self._docker_run(docker_img, cmd, envvars)
        # commit the docker img with the same 'docker_img'
        container.commit(docker_img)
        # TODO Terminate the container?

    def build(self, base_docker_img=DEfAULT_DOCKER_IMG, path_dockerfile="", debug=False):
        """
        @param base_docker_img: Docker image that Dockerfile starts with. This must be supplied.
        """
        # If prerequisite not met, exit the entire process.
        try:
            self.check_prerequisite()
        except RuntimeError as e:
            logging.error(str(e))
            exit(1)

        #self.docker_login()

        # copy resources
        tobe_copied = [path_dockerfile, entrypt_bin]
        tmp_dir = "/tmp/{}".format(datetime.datetime.fromtimestamp(time.time()).strftime('%Y%m%d%H%M%S'))
        if self._user_args.path_repos:
            tobe_copied.append(self._user_args.path_repos)
        elif self._user_args.volume_build:
            tobe_copied.append(self._user_args.volume_build)
        self.copy(tmp_dir, tobe_copied)
        os.chdir(tmp_dir)

        # TODO if volume mount build, copy the files in the volume. 

        logging.debug("path_dockerfile: {}, base_docker_img: {}, path_repos: {}".format(path_dockerfile, base_docker_img, path_repos))
        self.docker_build(path_dockerfile, base_docker_img, path_repos, rm_intermediate=False, debug=debug)
        
        return True

    def main(self):
        _MSG_LIMITATION_VOLUME = "For now this cannot be defined multiple times, as opposed to 'docker run' where multiple '-v' can be passed to."

        parser = argparse.ArgumentParser(description=DESC_DBUILDER)
        ## For now assume dockerfile
        # Optional args
        parser.add_argument("--debug", help="Disabled by default.", action="store_true")
        parser.add_argument("--docker_base_img", help="Image Dockerfile begins with.", default=DockerBuilderVCS.DEfAULT_DOCKER_IMG)
        parser.add_argument("--dockerfile", help="Dockerfile path to be used to build the Docker image with. This can be remote. Default is './{}'.".format(DockerBuilderVCS.DEfAULT_DOCKERFILE))
        parser.add_argument("--log_file", help="If defined, std{out, err} will be saved in a file. If not passed output will be streamed.", action="store_true")
        parser.add_argument("--push_cloud", help="If defined, not pushing the resulted Docker image to the cloud.", action="store_false")
        parser.add_argument("--rm_intermediate", help="If False, the intermediate Docker images are not removed.", action="store_true")
        parser.add_argument("--workspace_in_container", help="Workspace where the software obtained from vcs will be copied into. Also by default install space will be under this dir.", default="/cws")
        parser.add_argument("--workspace_on_host", help="Current dir, as Docker's context shouldn't change in order for Dockerfile to be accessible.", default=".")
        gr_src_to_build = parser.add_mutually_exclusive_group()
        gr_src_to_build.add_argument("--path_repos", help="Path to .repos file to clone and build in side the container/image.")
        gr_src_to_build.add_argument("--volume", help="""
                               Not implemented yet. Bind volume mount. Unlike '--volume_build' option, this doesn't do anything but mounting.
                               Anything you want to happen can be defined in your 'Dockerfile'.
                               {}""".format(_MSG_LIMITATION_VOLUME))
        gr_src_to_build.add_argument("--volume_build", help="""
                               The path to be bound as volume mount. Sources in this path will be built into Docker container.
                               If you're passing 'Dockerfile' and do some operations with mounted volume, use '--volume' option instead.
                               {}""".format(_MSG_LIMITATION_VOLUME))

        args = parser.parse_args()
        self.init(args)
    #    dockerbuilder.init(
    #        debug=args.debug,
    #        log_file=args.log_file,
    #        push_cloud=args.push_cloud,
    #    )
        return self.build(args.docker_base_img, args.dockerfile, args.debug)


if __name__ == '__main__':
    dockerbuilder = DockerBuilderVCS()
    dockerbuilder.main()
