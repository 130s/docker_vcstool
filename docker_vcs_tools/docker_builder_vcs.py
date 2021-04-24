#! /usr/bin/env python3

# Copyright (C) 2021 Kinu Garage
# Licensed under Apache 2

import argparse
import datetime
import docker
from io import BytesIO
import logging
import os
import subprocess
import sh
import shlex
import shutil
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
    DEfAULT_DOCKERTAG = "dockerimg_built"
    TOPDIR_SRC = "src"  # This folder name seems requirement for Catkin
    _MSG_LIMITATION_SRC_LOCATION = "There may be usecases to use both 'volume_build' and 'path_repos', which is not yet covered as the need is unclear."

    def __init__(self):
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

    def _docker_build_exec_api(self, path_dockerfile, baseimg, outimg="", rm_intermediate=True, entrypt_bin="", path_context=".", debug=False):
        """
        @brief Execute docker Python API via its lower-level API.
        @param path_context: Path of the directory'path_dockerfile' is located in.
        """
        dockerfile = os.path.basename(path_dockerfile)
        logging.info("Current dir before docker build: {}, dockerfile: {}".format(os.path.abspath(os.path.curdir), dockerfile))
        
        dck_api = docker.APIClient()

        #fobj = BytesIO(dockerfile.encode('utf-8'))
        _resp_docker_build = [line for line in dck_api.build(
            buildargs={"BASE_DIMG": baseimg,
                       "ENTRY_POINT": entrypt_bin,
                       "WS_IN_CONTAINER": self._workspace_in_container},
            dockerfile=dockerfile,
        #    fileobj=fobj,
            path=path_context,
            quiet=debug,
            rm=rm_intermediate,
            tag=outimg
        )]
        return _resp_docker_build

    def _docker_build_exec_noapi(self, path_dockerfile, baseimg, outimg="", rm_intermediate=True, entrypt_bin="", debug=False):
        """
        @deprecated: Not planned to be maintained. Use docker_build instead. This uses docker-py's method that misses some capability.
        @brief Execute docker Python API via its lower-level API.
        """
        img, _log = self._docker_client.images.build(
            dockerfile=os.path.basename(path_dockerfile),
            buildargs={"BASE_DIMG": baseimg,
                       "ENTRY_POINT": entrypt_bin,
                       "WS_IN_CONTAINER": self._workspace_in_container},
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

    def copy(self, src_list_files, dest_dir):
        """
        @summary: If the some files (e.g. dockerfile) that 'docker build' uses are not under current dir,
            1. copy them in the temp folder on the host.
            2. CD into the temp folder so that 'docker build' run in that context.
        @param src_list_files: Absolute or relative path to a folder or file to be copied. 
        """
        logging.info("Src list: {}, Destination dir {}".format(src_list_files, dest_dir))
        if not os.path.isdir(dest_dir):
            logging.info("Destination dir '{}' does not exist. Making it now.'".format(dest_dir))
            os.makedirs(dest_dir)
        for src_file_path in src_list_files:
            logging.info("To be copied: '{}'".format(src_file_path))
            # Python...I found copy cannot be done with the same method per dir and file.
            if os.path.isdir(src_file_path):
                abs_path_src = src_file_path if os.path.isabs(src_file_path) else os.path.abspath(src_file_path)
                #abs_path_dest = dest_dir if os.path.isabs(dest_dir) else os.path.join(dest_dir, path)
                abs_path_dest = os.path.join(dest_dir, os.path.basename(src_file_path))
                #os.makedirs(abs_path_dest, exist_ok=True)
                logging.info("Dir '{}' (absolute: {}) to be copied into: '{}'".format(src_file_path, abs_path_src, abs_path_dest))
                shutil.copytree(os.path.abspath(src_file_path), abs_path_dest)
            else:
                shutil.copy2(src_file_path, dest_dir)
        logging.info("Files are copied into a temp dir: '{}'".format(os.listdir(dest_dir)))
        return dest_dir

    def docker_build(
            self,
            path_dockerfile, baseimg, outimg="", rm_intermediate=True, tag=DEfAULT_DOCKERTAG, entrypt_bin="entry_point.bash", debug=False):
        """
        @brief Run 'docker build' using 'lower API version' https://docker-py.readthedocs.io/en/stable/api.html#module-docker.api.build.
            See also  https://github.com/docker/docker-py/issues/1400#issuecomment-273682010 for why lower API.
        @param tag: Tag for the Docker image to be built.
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

        logging.debug("Current dir before docker build: {}".format(os.path.abspath(os.path.curdir)))

        _log = None

        try:
            _log = self._docker_build_exec_api(
                path_dockerfile, baseimg, outimg=tag, rm_intermediate=False, debug=debug)
        except docker.errors.BuildError as e:
            logging.error("'docker build' failed: {}".format(str(e)))
            _log = e.build_log
            raise e
        except Exception as e:
            logging.error("'docker build' failed: {}".format(str(e)))
            raise e
        try:
            for line in _log:
                if 'stream' in line:
                    logging.error(line['stream'].strip())
        except TypeError as e:
            logging.error("Tentatively disabling logging the result of docker build due to the exception: {}".format(e))
        return True
        
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
        tobe_copied = [path_dockerfile]
        tmp_docker_context_dir = "/tmp/{}".format(datetime.datetime.fromtimestamp(time.time()).strftime('%Y%m%d%H%M%S'))
        # Appending resources to be copied into Docker. For now
        if self._user_args.path_repos:
            logging.info("'path_repos' is set. Clone locally from the repositories defined in the given .repos file.")
            tmp_dockercontext_srcdir = os.path.join(tmp_docker_context_dir, self.TOPDIR_SRC)
            os.makedirs(tmp_dockercontext_srcdir, exist_ok=True)
            logging.info("Build tools may require the top dir name to be '{}' for the source. Temporary source dir created: '{}'".format(self.TOPDIR_SRC, tmp_dockercontext_srcdir))
            os.chdir(tmp_docker_context_dir)
            debug_arg = "--debug" if debug else ""
            _CMD_VCS = "vcs import {} --skip-existing {}/{} < {}".format(debug_arg, tmp_docker_context_dir, self.TOPDIR_SRC, self._user_args.path_repos)
            subprocess.run(shlex.split(_CMD_VCS), capture_output=True)
            tobe_copied.append(tmp_dockercontext_srcdir)
        elif self._user_args.volume_build:
            logging.info("'volume_build' is set. All files and folders under the volume dir '{}' are to be copied into the workspace.".format(self._user_args.volume_build))
            if not self._user_args.volume_build.endswith(self.TOPDIR_SRC):
                logging.info("The mounted top dir name '{}' is not 'src', then not adding the top dir to tobe_copied.".format(self._user_args.volume_build))
                for f in os.listdir(self._user_args.volume_build):
                    self.copy(f, tmp_dockercontext_srcdir)
            tobe_copied.append(self._user_args.volume_build)
        self.copy(tobe_copied, tmp_docker_context_dir)
        os.chdir(tmp_docker_context_dir)

        logging.info("path_dockerfile: {}, base_docker_img: {}, tmp Docker context dir: {}".format(path_dockerfile, base_docker_img, tmp_docker_context_dir))
        self.docker_build(path_dockerfile, base_docker_img, rm_intermediate=False, debug=debug)
        
        return True

    def main(self):
        _MSG_LIMITATION_VOLUME = ("For now this cannot be defined multiple times, as opposed to 'docker run' where multiple '-v's can be passed to."
                                  "Therefore the value passed to this needs to be the ***top directory*** of all source folders to be built, e.g. 'src'.")

        parser = argparse.ArgumentParser(description=DESC_DBUILDER)
        ## For now assume dockerfile
        # Optional args
        parser.add_argument("--debug", help="Disabled by default.", action="store_true")
        parser.add_argument("--docker_base_img", help="Image Dockerfile begins with.", default=DockerBuilderVCS.DEfAULT_DOCKER_IMG)
        parser.add_argument("--dockerfile", help="Dockerfile path to be used to build the Docker image with. This can be remote. Default is './{}'.".format(DockerBuilderVCS.DEfAULT_DOCKERFILE))
        parser.add_argument("--docker_image_tag", help="Tag for the Docker image to be built. Default is './{}'.".format(DockerBuilderVCS.DEfAULT_DOCKERTAG))
        parser.add_argument("--log_file", help="If defined, std{out, err} will be saved in a file. If not passed output will be streamed.", action="store_true")
        parser.add_argument("--push_cloud", help="If defined, not pushing the resulted Docker image to the cloud.", action="store_false")
        parser.add_argument("--rm_intermediate", help="If False, the intermediate Docker images are not removed.", action="store_true")
        parser.add_argument("--workspace_in_container", help="Workspace where the software obtained from vcs will be copied into. Also by default install space will be under this dir.", default="/cws")
        parser.add_argument("--workspace_on_host", help="Current dir, as Docker's context shouldn't change in order for Dockerfile to be accessible.", default=".")
        gr_src_to_build = parser.add_mutually_exclusive_group()
        gr_src_to_build.add_argument("--path_repos", help="Path to .repos file to clone and build in side the container/image. {}".format(self._MSG_LIMITATION_SRC_LOCATION))
        gr_src_to_build.add_argument("--volume", help="""
                               Not implemented yet. Bind volume mount. Unlike '--volume_build' option, this doesn't do anything but mounting.
                               Anything you want to happen can be defined in your 'Dockerfile'.
                               {}""".format(_MSG_LIMITATION_VOLUME))
        gr_src_to_build.add_argument("--volume_build", help="""
                               The path to be bound as volume mount. Sources in this path will be targeted to build into Docker container.
                               {} {}""".format(_MSG_LIMITATION_VOLUME, self._MSG_LIMITATION_SRC_LOCATION))

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
