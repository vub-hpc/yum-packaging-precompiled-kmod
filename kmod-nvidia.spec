# We disable stripping here and do it ourselves later
%global __strip /bin/true
%global __os_install_post %{nil}
# build ids are disabled since we might be shipping the exact same
# ld.gold binary that's also installed on the user system. In that
# case, the build id files would conflict.
%global _build_id_links none

# Named version, usually just the driver version, or "latest"
%define _named_version %{driver_branch}

# Distribution name, like .el8 or .el8_1
%define kmod_dist %{?kernel_dist}%{?!kernel_dist:%{dist}}

%define kmod_vendor		nvidia
%define kmod_driver_version	%{driver}
# We use some default kernel (here the current RHEL 7.5 one) if
# there's no --define="kernel x.y.z" passed to rpmbuild
%define kmod_kernel		%{?kernel}%{?!kernel:3.10.0}
%define kmod_kernel_release	%{?kernel_release}%{?!kernel_release:862}
%define kmod_kernel_version	%{kmod_kernel}-%{kmod_kernel_release}%{kmod_dist}
%define kmod_kbuild_dir		drivers/video/nvidia
%define kmod_module_path	/lib/modules/%{kmod_kernel_version}.%{_arch}/extra/%{kmod_kbuild_dir}
%define kmod_share_dir		%{_prefix}/share/nvidia-%{kmod_kernel_version}
# NOTE: We disambiguate the installation path of the .o files twice, once for the driver version
# and once for the kernel version. This might not be necessary (in the future).
%define kmod_o_dir		%{_libdir}/nvidia/%{_target}/%{kmod_driver_version}/%{kmod_kernel_version}
%define kmod_modules		nvidia nvidia-uvm nvidia-modeset nvidia-drm nvidia-peermem
# For compatibility with upstream Negativo17 shell scripts, we use nvidia-kmod
# instead of kmod-nvidia for the source tarball.
%define kmod_source_name	%{kmod_vendor}-kmod-%{kmod_driver_version}-%{_arch}
%define kmod_kernel_source	/usr/src/kernels/%{kmod_kernel_version}.%{_arch}

# File was renamed in v5.10+ with 'kbuild: preprocess module linker script'
%if 0%{?rhel} >= 9 || 0%{?fedora}
	%global module_lds module.lds
%else
	%global module_lds module-common.lds
%endif

# Global re-define for the strip command we apply to all the .o files
%define strip strip -g --strip-unneeded

# We always use ld.gold since that one does not dynamically link
# against a libgold or similar. ld.bfd does.
%define _ld %{_bindir}/ld.gold
# postld is the ld version we ship ourselves, install and then use
# in %post to link the final kernel module
%define postld %{_bindir}/ld.gold.nvidia.%{kmod_driver_version}.%{kmod_kernel_version}

%define debug_package %{nil}
%define sbindir %( if [ -d "/sbin" -a \! -h "/sbin" ]; then echo "/sbin"; else echo %{_sbindir}; fi )

Source0:	%{kmod_source_name}.tar.xz
%if 0%{?hsm} == 0
Source1:	private_key.priv
Source2:	public_key.der
%else
Source3:    %{hsm_wrapper_script}
%endif


Name:		kmod-%{kmod_vendor}-%{_named_version}
Version:	%{kmod_kernel}
Release:	%{kmod_kernel_release}.r%{kmod_driver_version}%{kmod_dist}
Summary:	NVIDIA graphics driver
Group:		System/Kernel
License:	Nvidia
Epoch:		3
URL:		http://www.nvidia.com/
BuildRoot:	%(mktemp -ud %{_tmppath}/%{name}-%{version}-%{release}-XXXXXX)
BuildRequires:	kernel-devel = %kmod_kernel_version
BuildRequires:	redhat-rpm-config
BuildRequires:	elfutils-libelf-devel
BuildRequires:	%{_ld}
BuildRequires:	openssl
ExclusiveArch:	x86_64 ppc64le aarch64

%if 0%{?rhel} == 7
	%global _use_internal_dependency_generator 0
%endif
Provides:		kernel-modules = %kmod_kernel_version.%{_target_cpu}
# Meta-provides for all nvidia kernel modules. The precompiled version and the
# DKMS kernel module package both provide this and the driver package only needs
# one of them to satisfy the dependency.
Provides:		nvidia-kmod = %{?epoch:%{epoch}:}%{kmod_driver_version}
Requires(post):		/usr/bin/strip

Conflicts:      kmod-nvidia-latest-dkms
Provides:       kmod-nvidia-latest-dkms = %{kmod_driver_version}-1%{kmod_dist}

%if 0%{?rhel} >= 8 || 0%{?fedora}
Supplements: (nvidia-driver = %{epoch}:%{kmod_driver_version} and kernel = %{kmod_kernel_version})
# We cannot require the version of the driver in the kmod package since
# dnf won't remove the kmod package automatically when enabling a different
# module stream. This will cause the transaction to fail.
#Requires:	nvidia-driver = %%{epoch}:%%{version}

# This works though and will automatically remove the kmod package when removing
# the kernel package.
Requires: (kernel = %{kmod_kernel_version} if kernel)
Conflicts: kmod-nvidia-latest-dkms
%endif

%description
The NVidia %{kmod_driver_version} display driver kernel module for kernel %{kmod_kernel_version}

%prep
%setup -q -n %{kmod_source_name}

%build
cd kernel
# A proper kernel module build uses /lib/modules/KVER/{source,build} respectively,
# but that creates a dependency on the 'kernel' package since those directories are
# not provided by kernel-devel. Both /source and /build in the mentioned directory
# just link to the sources directory in /usr/src however, which ddiskit defines
# as kmod_kernel_source.
KERNEL_SOURCES=%{kmod_kernel_source}
KERNEL_OUTPUT=%{kmod_kernel_source}
#KERNEL_SOURCES=/lib/modules/%{kmod_kernel_version}.%{_target_cpu}/source/
#KERNEL_OUTPUT=/lib/modules/%{kmod_kernel_version}.%{_target_cpu}/build


# These could affect the linking so we unset them both there and in %post
unset LD_RUN_PATH
unset LD_LIBRARY_PATH


#
# Compile kernel modules
#
%if 0%{?hsm} == 0 || 0%{?hsm} == 1
%{make_build} SYSSRC=${KERNEL_SOURCES} SYSOUT=${KERNEL_OUTPUT}

# These will be used together with the .mod.o file as input for ld,
# which links the .ko. To keep the file size down and *make it more deterministic*,
# we strip them here.
%{strip} nvidia/nv-interface.o
%{strip} nvidia-uvm.o
%{strip} nvidia-drm.o
%{strip} nvidia-peermem/nvidia-peermem.o
%{strip} nvidia-modeset/nv-modeset-interface.o

# Just to be safe
rm nvidia.o
rm nvidia-modeset.o

# Link our own nvidia.o and nvidia-modeset.o from the -interface.o and the -kernel.o.
# This is necessary because we just stripped the input .o files
%{_ld} -r -o nvidia.o nvidia/nv-interface.o nvidia/nv-kernel.o
%{_ld} -r -o nvidia-modeset.o nvidia-modeset/nv-modeset-interface.o nvidia-modeset/nv-modeset-kernel.o
%{_ld} -r -o nvidia-peermem.o nvidia-peermem/nvidia-peermem.o

# The build above has already linked a module.ko, but we do it again here
# so we can first %{strip} the module.o, which we also do at installation time.
# This way we ensure equal nvidia.o files, which will also result in equal
# build-ids.
for m in %{kmod_modules}; do
	%{strip} ${m}.o --keep-symbol=init_module --keep-symbol=cleanup_module
	rm ${m}.ko

	%{_ld} -r \
		-z max-page-size=0x200000 -T %{kmod_kernel_source}/scripts/%{module_lds} \
		--build-id -r \
		-o ${m}.ko \
		${m}.o \
		${m}.mod.o
done
%endif


# We don't want to require kernel-devel at installation time on the user system, so we
# copy the module*.lds of the kernel we're building against into the package.
cp %{kmod_kernel_source}/scripts/%{module_lds} .

# Copy linker
cp %{_ld} .


# Use two pass rpmbuild when signing using a HSM
# First  rpmbuild --define "hsm 1" -bc
# Second rpmbuild --define "hsm 2" -bc --short-circuit
# Third  rpmbuild --define "hsm 2" -bi --short-circuit
# Four   rpmbuild --define "hsm 2" -bb --short-circuit

# First pass, no signing
%if 0%{?hsm} == 1
echo "HSM part 1"
pwd
for m in %{kmod_modules}; do
    du -b "${m}.ko"
    %{SOURCE3} ${m} %{name}
done

# Use HSM signed modules
# Detach the signatures from each .ko
# Ship only the signature portion
%elif 0%{?hsm} == 2
echo "HSM part 2"
for m in %{kmod_modules}; do
    [[ -f ${m}.ko-signature ]] || exit 1
	ko_size=`du -b "${m}.ko" | cut -f1`
	tail ${m}.ko-signature -c +$(($ko_size + 1)) > ${m}.sig
done
%endif

%post
unset LD_RUN_PATH
unset LD_LIBRARY_PATH
cd %{kmod_o_dir}
mkdir -p %{kmod_module_path}
chmod +x %{postld}

# link nvidia.o
%{postld} -z max-page-size=0x200000 -r \
	-o nvidia.o \
	nvidia/nv-interface.o \
	nvidia/nv-kernel.o

%{strip} nvidia.o
%{postld} -r -T %{kmod_share_dir}/%{module_lds} --build-id -o %{kmod_module_path}/nvidia.ko nvidia.o nvidia.mod.o
rm nvidia.o

# nvidia-uvm.o
%{postld} -r -T %{kmod_share_dir}/%{module_lds} --build-id -o %{kmod_module_path}/nvidia-uvm.ko nvidia-uvm/nvidia-uvm.o nvidia-uvm.mod.o

# nvidia-modeset.o
%{postld} -z max-page-size=0x200000 -r \
	-o nvidia-modeset.o \
	nvidia-modeset/nv-modeset-interface.o \
	nvidia-modeset/nv-modeset-kernel.o

%{strip} nvidia-modeset.o
%{postld} -r -T %{kmod_share_dir}/%{module_lds} --build-id -o %{kmod_module_path}/nvidia-modeset.ko nvidia-modeset.o nvidia-modeset.mod.o
rm nvidia-modeset.o

#nvidia-drm.o
%{postld} -r -T %{kmod_share_dir}/%{module_lds} --build-id -o %{kmod_module_path}/nvidia-drm.ko nvidia-drm/nvidia-drm.o nvidia-drm.mod.o

# nvidia-peermem.o
%{postld} -r -T %{kmod_share_dir}/%{module_lds} --build-id -o %{kmod_module_path}/nvidia-peermem.ko nvidia-peermem/nvidia-peermem.o nvidia-peermem.mod.o

depmod -a %{kmod_kernel_version}.%{_arch}

%postun
depmod -a %{kmod_kernel_version}.%{_arch}


%install
mkdir -p %{buildroot}/%{kmod_o_dir}
mkdir -p %{buildroot}/%{kmod_o_dir}/nvidia/
mkdir -p %{buildroot}/%{kmod_o_dir}/nvidia-uvm/
mkdir -p %{buildroot}/%{kmod_o_dir}/nvidia-modeset/
mkdir -p %{buildroot}/%{kmod_o_dir}/nvidia-drm/
mkdir -p %{buildroot}/%{kmod_o_dir}/nvidia-peermem/
mkdir -p %{buildroot}/%{kmod_share_dir}
mkdir -p %{buildroot}/%{_bindir}

# for every kernel module, we ship all the necessary
# .o files as well as a .mod.o generated by modpost
# and a .sig file which contains the signature
# of the signed, linked .ko module

cd kernel
# driver
install nvidia.mod.o %{buildroot}/%{kmod_o_dir}/
install nvidia/nv-interface.o %{buildroot}/%{kmod_o_dir}/nvidia/
install nvidia/nv-kernel.o_binary %{buildroot}/%{kmod_o_dir}/nvidia/nv-kernel.o

# uvm
install nvidia-uvm.mod.o %{buildroot}/%{kmod_o_dir}/
install nvidia-uvm.o %{buildroot}/%{kmod_o_dir}/nvidia-uvm/

# modeset
install nvidia-modeset.mod.o %{buildroot}/%{kmod_o_dir}/
install nvidia-modeset/nv-modeset-interface.o %{buildroot}/%{kmod_o_dir}/nvidia-modeset/
install nvidia-modeset/nv-modeset-kernel.o %{buildroot}/%{kmod_o_dir}/nvidia-modeset/

# drm
install nvidia-drm.mod.o %{buildroot}/%{kmod_o_dir}/
install nvidia-drm.o %{buildroot}/%{kmod_o_dir}/nvidia-drm/

# peermem
install nvidia-peermem.mod.o %{buildroot}/%{kmod_o_dir}/
install nvidia-peermem.o %{buildroot}/%{kmod_o_dir}/nvidia-peermem/

# misc
install -m 644 -D %{module_lds} %{buildroot}/%{kmod_share_dir}/

install -m 755 ld.gold %{buildroot}/%{postld}


%files
%defattr(644,root,root,755)

%{kmod_o_dir}
%{kmod_share_dir}
%{postld}

%ghost %{kmod_module_path}
%ghost %{kmod_module_path}/nvidia.ko
%ghost %{kmod_module_path}/nvidia-uvm.ko
%ghost %{kmod_module_path}/nvidia-drm.ko
%ghost %{kmod_module_path}/nvidia-peermem.ko
%ghost %{kmod_module_path}/nvidia-modeset.ko

%clean
rm -rf $RPM_BUILD_ROOT

%changelog
* Tue Nov 16 2021 Alex Domingo <alex.domingo.toro@vub.be>
 - Fix conflict resolution with kmod-nvidia-latest-dkms
 - Disable module signing
 - Roll back RPM navimg scheme to static names

* Wed Jul 07 2021 Kevin Mittman <kmittman@nvidia.com>
 - Add two-pass HSM certificate signing flow

* Tue Apr 27 2021 Kevin Mittman <kmittman@nvidia.com>
 - Unofficial support for ppc64le and aarch64

* Wed Mar 31 2021 Kevin Mittman <kmittman@nvidia.com>
 - Kernels version 5.10+ rename modules-common.lds to modules.lds

* Mon Feb 08 2021 Kevin Mittman <kmittman@nvidia.com>
 - Add nvidia-peermem module

* Wed Oct 21 2020 Kevin Mittman <kmittman@nvidia.com>
 - Include architecture in depmod command

* Fri Oct 09 2020 Kevin Mittman <kmittman@nvidia.com>
 - Run depmod for target kernel version, not running kernel

* Thu May 07 2020 Timm Bäder <tbaeder@redhat.com>
 - List generated files as %%ghost files
 - Only require the kernel if any kernel is installed

* Thu Apr 30 2020 Kevin Mittman <kmittman@nvidia.com>
 - Unique ld.gold filename

* Tue Apr 28 2020 Timm Bäder <tbaeder@redhat.com>
 - Removed unused kmod_rpm_release variable
 - Fix kernel_dist fallback to %%{dist}
 - Remove -m elf_x86_64 argument from linker invocations
 - Add /usr/bin/strip requirement for %%post scriptlet
 - Conflict with kmod-nvidia-latest-dkms, not dkms-nvidia

* Fri Dec 06 2019 Kevin Mittman <kmittman@nvidia.com>
 - Pass %{kernel_dist} as it may not match the system %{dist}

* Fri Jun 07 2019 Kevin Mittman <kmittman@nvidia.com>
 - Rename package, Change Requires, Remove %ghost

* Fri May 24 2019 Kevin Mittman <kmittman@nvidia.com>
 - Fixes for yum swap including %ghost and removal of postun actions

* Fri May 17 2019 Kevin Mittman <kmittman@nvidia.com>
 - Change Requires: s/nvidia-driver/nvidia-driver-%{driver_branch}/

* Fri Apr 12 2019 Kevin Mittman <kmittman@nvidia.com>
 - Change to kmod-nvidia-branch-AAA-X.XX.X-YYY.Y.Y.rAAA.BB.BB.el7.arch.rpm

* Mon Mar 11 2019 Kevin Mittman <kmittman@nvidia.com>
 - Remove %{_name_version} from Requires and Supplments

* Fri Mar 08 2019 Kevin Mittman <kmittman@nvidia.com>
 - Change from kmod-nvidia-branch-XXX-Y.YY.Y-YYYY.1.el7..rpm to kmod-nvidia-XXX.XX.XX-Y.YY.Y-YYY.el7..rpm

* Thu Mar 07 2019 Kevin Mittman <kmittman@nvidia.com>
 - Initial .spec from Timm Bäder

