If you would like to contribute to the development of OpenStack, you must
follow the steps in this page:

   https://docs.openstack.org/infra/manual/developers.html

If you already have a good understanding of how the system works and your
OpenStack accounts are set up, you can skip to the development workflow
section of this documentation to learn how changes to OpenStack should be
submitted for review via the Gerrit tool:

   https://docs.openstack.org/infra/manual/developers.html#development-workflow

Pull requests submitted through GitHub will be ignored.

Bugs should be filed on Launchpad, not GitHub:

   https://bugs.launchpad.net/kuryr-kubernetes

If you want to have your code checked for pep8 automatically before committing
changes, you can just do::

    pip install pre-commit
    pre-commit install

From that moment on, every time you run *git commit* it will first check your
diff for pep8 compliance and refuse to commit if it doesn't pass.
