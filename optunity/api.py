#! /usr/bin/env python

# Copyright (c) 2014 KU Leuven, ESAT-STADIUS
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# 1. Redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.
#
# 3. Neither name of copyright holders nor the names of its contributors
# may be used to endorse or promote products derived from this software
# without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# ``AS IS'' AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL THE REGENTS OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""A collection of top-level API functions for Optunity.

Main functions in this module:

* :func:`make_solver`
* :func:`suggest_solver`
* :func:`manual`
* :func:`maximize`
* :func:`maximize_structured`
* :func:`minimize`
* :func:`minimize_structured`
* :func:`optimize`

We recommend using these functions rather than equivalents found in other places,
e.g. :mod:`optunity.solvers`.

.. moduleauthor:: Marc Claesen

"""

import timeit
import sys
import operator
import pickle
import os
import time

# optunity imports
import warnings

from . import functions as fun
from . import solvers
from . import search_spaces
from .solvers import solver_registry
from .util import DocumentedNamedTuple as DocTup
from .constraints import wrap_constraints


def _manual_lines(solver_name=None):
    """Brief solver manual.

    :param solver_name: (optional) name of the solver to request a manual from.
        If none is specified, a general manual and list of all registered solvers is returned.

    :result:
        * list of strings that contain the requested manual
        * solver name(s): name of the solver that was specified or list of all registered solvers.

    Raises ``KeyError`` if ``solver_name`` is not registered."""
    if solver_name:
        return solver_registry.get(solver_name).desc_full, [solver_name]
    else:
        return solver_registry.manual(), solver_registry.solver_names()


def available_solvers():
    """Returns a list of all available solvers.

    These can be used in :func:`optunity.make_solver`.
    """
    return solver_registry.solver_names()


def manual(solver_name=None):
    """Prints the manual of requested solver.

    :param solver_name: (optional) name of the solver to request a manual from.
        If none is specified, a general manual is printed.

    Raises ``KeyError`` if ``solver_name`` is not registered."""
    if solver_name:
        man = solver_registry.get(solver_name).desc_full
    else:
        man = solver_registry.manual()
    print('\n'.join(man))


optimize_results = DocTup("""
**Result details includes the following**:

optimum
    optimal function value f(solution)

stats
    statistics about the solving process

call_log
    the call log

report
    solver report, can be None
                          """,
                          'optimize_results', ['optimum',
                                               'stats',
                                               'call_log',
                                               'report']
                          )
optimize_stats = DocTup("""
**Statistics gathered while solving a problem**:

num_evals
    number of function evaluations
time
    wall clock time needed to solve
                        """,
                        'optimize_stats', ['num_evals', 'time'])


def suggest_solver(num_evals=50, solver_name=None, **kwargs):
    if solver_name:
        solvercls = solver_registry.get(solver_name)
    else:
        solver_name = 'particle swarm'
        solvercls = solvers.ParticleSwarm
    if hasattr(solvercls, 'suggest_from_box'):
        suggestion = solvercls.suggest_from_box(num_evals, **kwargs)
    elif hasattr(solvercls, 'suggest_from_seed'):
        # the seed will be the center of the box that is provided to us
        seed = dict([(k, float(v[0] + v[1]) / 2) for k, v in kwargs.items()])
        suggestion = solvercls.suggest_from_seed(num_evals, **seed)
    else:
        raise ValueError('Unable to instantiate ' + solvercls.name + '.')
    suggestion['solver_name'] = solver_name
    return suggestion


def maximize(f, num_evals=50, solver_name=None, pmap=map, save_dir=None, restore_file_path=None, **kwargs):
    """Basic function maximization routine. Maximizes ``f`` within
    the given box constraints.

    :param f: the function to be maximized
    :param num_evals: number of permitted function evaluations
    :param solver_name: name of the solver to use (optional)
    :type solver_name: string
    :param pmap: the map function to use
    :type pmap: callable
    :param kwargs: box constraints, a dict of the following form
        ``{'parameter_name': [lower_bound, upper_bound], ...}``
    :returns: retrieved maximum, extra information and solver info

    This function will implicitly choose an appropriate solver and
    its initialization based on ``num_evals`` and the box constraints.

    """
    # sanity check on box constraints
    assert all([len(v) == 2 and v[0] < v[1]
                for v in kwargs.values()]), 'Box constraints improperly specified: should be [lb, ub] pairs'

    f = _wrap_hard_box_constraints(f, kwargs, -sys.float_info.max)

    suggestion = suggest_solver(num_evals, solver_name, **kwargs)
    solver = make_solver(**suggestion)
    solution, details = optimize(solver, f, maximize=True, max_evals=num_evals,
                                 pmap=pmap, save_dir=save_dir, restore_file_path=restore_file_path)
    return solution, details, suggestion


def minimize(f, num_evals=50, solver_name=None, pmap=map, save_dir=None, restore_file_path=None, **kwargs):
    """Basic function minimization routine. Minimizes ``f`` within
    the given box constraints.

    :param f: the function to be minimized
    :param num_evals: number of permitted function evaluations
    :param solver_name: name of the solver to use (optional)
    :type solver_name: string
    :param pmap: the map function to use
    :type pmap: callable
    :param kwargs: box constraints, a dict of the following form
        ``{'parameter_name': [lower_bound, upper_bound], ...}``
    :returns: retrieved minimum, extra information and solver info

    This function will implicitly choose an appropriate solver and
    its initialization based on ``num_evals`` and the box constraints.

    """
    # sanity check on box constraints
    assert all([len(v) == 2 and v[0] < v[1]
                for v in kwargs.values()]), 'Box constraints improperly specified: should be [lb, ub] pairs'

    func = _wrap_hard_box_constraints(f, kwargs, sys.float_info.max)

    suggestion = suggest_solver(num_evals, solver_name, **kwargs)
    solver = make_solver(**suggestion)
    solution, details = optimize(solver, func, maximize=False, max_evals=num_evals,
                                 pmap=pmap, save_dir=save_dir, restore_file_path=restore_file_path)
    return solution, details, suggestion


def optimize(solver, func, maximize=True, max_evals=0, pmap=map, decoder=None, save_dir=None, restore_file_path=None):
    """Optimizes func with given solver.

    :param solver: the solver to be used, for instance a result from :func:`optunity.make_solver`
    :param func: the objective function
    :type func: callable
    :param maximize: maximize or minimize?
    :type maximize: bool
    :param max_evals: maximum number of permitted function evaluations
    :type max_evals: int
    :param pmap: the map() function to use, to vectorize use :func:`optunity.parallel.pmap`
    :type pmap: function
    :param save_dir: directory where we wish to save the evaluations.
    :param restore_file_path: file from which we wish to restore our evaluations.

    Returns the solution and a namedtuple with further details.
    Please refer to docs of optunity.maximize_results
    and optunity.maximize_stats.

    This file was modified to introduce the possibility to save the progress of the optimization.
    If you wish to save or restore or both, please provide the required parameters.


    """

    # This variable is used for saving purposes.
    original_max_evals = max_evals

    saved_f = None
    if restore_file_path:
        # A restore file path was provided.
        with open(restore_file_path, 'rb') as f_handler:
            saved_f = pickle.load(f_handler)
    else:
        # A restore file path was provided. A save dir was provided but the new evaluations might overwrite an existing
        # file with the same name.
        # We ask the user if she wants to continue training or abort it.
        if save_dir:
            if os.path.isfile(os.path.join(save_dir, 'optunity_save_{}_evals.pkl'.format(original_max_evals))):
                valid = {"yes": True, "y": True, "ye": True,
                         "no": False, "n": False}
                print('######## WARNING ########')
                print("You are about to overwrite an existing save.")
                print("Are you sure you want to proceed [y/n]:\n")
                while True:
                    choice = input().lower()
                    if choice in valid:
                        if valid[choice]:
                            print("Continuing the process !!!")
                            break
                        else:
                            print("Aborting run !!!")
                            sys.exit(999)
                    else:
                        sys.stdout.write("Please respond with 'yes' or 'no' "
                                         "(or 'y' or 'n').\n")

    if saved_f:
        # We are restoring.

        if max_evals == 0:
            # max_evals defaults to 0 when no value is provided.
            # In this case we use the max_evals that was saved in the pickle.
            original_max_evals = saved_f['max_evals']
            max_evals = saved_f['max_evals']

        # A hack to avoid skipping some evaluations.
        # We are now saving after each evaluation.
        # TODO: handle saving frequency as a variable
        missing_evals = max_evals // 2
        if max_evals % 2 == 0:
            max_evals += 2 * missing_evals - 1
        else:
            max_evals += 2 * missing_evals

        # The user might decide to reduce the number of evaluations.
        if max_evals - saved_f['num_evals'] <= 0:
            # If at the new number of iterations was already done. We inform the user and return the best results.
            print("Already done at least the correct number opf evaluations.")
            if max_evals > 0:
                f = fun.max_evals(max_evals)(func)
            else:
                f = func

            # How many evaluations we already did.
            f.num_evals = saved_f['num_evals']

            f = fun.logged(f)

            # Restore the log.
            while len(saved_f['log_data']) > 0:
                key, value = saved_f['log_data'].popitem()
                f.call_log.insert(value, **key._asdict())

            # We return the best solution.
            report = None
            if maximize:
                index, _ = max(enumerate(f.call_log.values()), key=operator.itemgetter(1))
            else:
                index, _ = min(enumerate(f.call_log.values()), key=operator.itemgetter(1))
            solution = list(f.call_log.keys())[index]._asdict()

            # This was in the original code.
            # TODO why is this necessary?
            if decoder:
                solution = decoder(solution)

            optimum = f.call_log.get(**solution)
            num_evals = len(f.call_log)

            # use namedtuple to enforce uniformity in case of changes
            stats = optimize_stats(num_evals, saved_f['elapsed_time'])

            call_dict = f.call_log.to_dict()
            return solution, optimize_results(optimum, stats._asdict(),
                                              call_dict, report)

        if max_evals > 0:
            f = fun.max_evals(max_evals)(func)
        else:
            f = func

        # How many evaluations we already did.
        f.num_evals = saved_f['num_evals']

        f = fun.logged(f)

        # Restore the log.
        while len(saved_f['log_data']) > 0:
            key, value = saved_f['log_data'].popitem()
            f.call_log.insert(value, **key._asdict())

        # Restoring the elapsed time.
        time_var = timeit.default_timer() - saved_f['elapsed_time']

    else:
        # We are not restoring.

        missing_evals = max_evals // 2
        if max_evals % 2 == 0:
            max_evals += 2 * missing_evals - 1
        else:
            max_evals += 2 * missing_evals

        if max_evals > 0:
            f = fun.max_evals(max_evals)(func)
        else:
            f = func

        f = fun.logged(f)

        time_var = timeit.default_timer()
    while True:
        try:
            # If we reload a file while we have already done the required number of evaluations, we just return the
            # best solution.
            if max_evals > 0:
                if saved_f and f.num_evals == max_evals:
                    raise fun.MaximumEvaluationsException(max_evals)

            solution, report = solver.optimize(f, maximize, pmap=pmap)

            # Break from the while loop once done.
            # We only get to this break if no exception was triggered.
            break
        except fun.ModuloEvaluationsException:
            # We need to save f in order for it to be used later.
            if save_dir:
                if saved_f:
                    # In this case we are updating the saved_file.
                    if len(f.call_log) == saved_f['max_evals']:
                        num_evaluations = max_evals
                    else:
                        num_evaluations = len(f.call_log)
                    dict_to_save = {'log_data': f.call_log.data, 'max_evals': original_max_evals,
                                    'num_evals': num_evaluations, 'elapsed_time': timeit.default_timer() - time_var}
                else:
                    # We are using a new file. (No restore file was provided).
                    if len(f.call_log) == original_max_evals:
                        num_evaluations = max_evals
                    else:
                        num_evaluations = len(f.call_log)
                    dict_to_save = {'log_data': f.call_log.data, 'max_evals': original_max_evals,
                                    'num_evals': num_evaluations, 'elapsed_time': timeit.default_timer() - time_var}
                # Saving the necessary information.
                with open(os.path.join(save_dir, 'optunity_save_{}_evals.pkl'.format(original_max_evals)), 'wb') \
                        as f_handler:
                    pickle.dump(dict_to_save, f_handler)
        except fun.MaximumEvaluationsException:
            # early stopping because maximum number of evaluations is reached
            # retrieve solution from the call log
            report = None
            if maximize:
                index, _ = max(enumerate(f.call_log.values()), key=operator.itemgetter(1))
            else:
                index, _ = min(enumerate(f.call_log.values()), key=operator.itemgetter(1))
            solution = list(f.call_log.keys())[index]._asdict()

            if save_dir:
                # If the user provided a path to save a pickle.
                if saved_f:
                    if len(f.call_log) == saved_f['max_evals']:
                        num_evaluations = max_evals
                    else:
                        num_evaluations = len(f.call_log)
                    dict_to_save = {'log_data': f.call_log.data, 'max_evals': original_max_evals,
                                    'num_evals': num_evaluations, 'elapsed_time': timeit.default_timer() - time_var}
                else:
                    # The user did not provide us with a path to save.
                    if len(f.call_log) == original_max_evals:
                        num_evaluations = max_evals
                    else:
                        num_evaluations = len(f.call_log)
                    dict_to_save = {'log_data': f.call_log.data, 'max_evals': original_max_evals,
                                    'num_evals': num_evaluations, 'elapsed_time': timeit.default_timer() - time_var}
                with open(os.path.join(save_dir, 'optunity_save_{}_evals.pkl'.format(original_max_evals)), 'wb') \
                        as f_handler:
                    pickle.dump(dict_to_save, f_handler)
            # No need to loop again
            break

    time_var = timeit.default_timer() - time_var

    # TODO why is this necessary?
    if decoder:
        solution = decoder(solution)

    optimum = f.call_log.get(**solution)
    num_evals = len(f.call_log)

    # use namedtuple to enforce uniformity in case of changes
    stats = optimize_stats(num_evals, time_var)

    call_dict = f.call_log.to_dict()
    return solution, optimize_results(optimum, stats._asdict(),
                                      call_dict, report)


optimize.__doc__ = '''
Optimizes func with given solver.

:param solver: the solver to be used, for instance a result from :func:`optunity.make_solver`
:param func: the objective function
:type func: callable
:param maximize: maximize or minimize?
:type maximize: bool
:param max_evals: maximum number of permitted function evaluations
:type max_evals: int
:param pmap: the map() function to use, to vectorize use :func:`optunity.pmap`
:type pmap: function

Returns the solution and a ``namedtuple`` with further details.
''' + optimize_results.__doc__ + optimize_stats.__doc__


def make_solver(solver_name, *args, **kwargs):
    """Creates a Solver from given parameters.

    :param solver_name: the solver to instantiate
    :type solver_name: string
    :param args: positional arguments to solver constructor.
    :param kwargs: keyword arguments to solver constructor.

    Use :func:`optunity.manual` to get a list of registered solvers.
    For constructor arguments per solver, please refer to :doc:`/user/solvers`.

    Raises ``KeyError`` if

    - ``solver_name`` is not registered
    - ``*args`` and ``**kwargs`` are invalid to instantiate the solver.

    """
    solvercls = solver_registry.get(solver_name)
    return solvercls(*args, **kwargs)


def wrap_call_log(f, call_dict):
    """Wraps an existing call log (as dictionary) around f.

    This allows you to communicate known function values to solvers.
    (currently available solvers do not use this info)

    """
    f = fun.logged(f)
    call_log = fun.CallLog.from_dict(call_dict)
    if f.call_log:
        f.call_log.update(call_log)
    else:
        f.call_log = call_log
    return f


def _wrap_hard_box_constraints(f, box, default):
    """Places hard box constraints on the domain of ``f``
    and defaults function values if constraints are violated.

    :param f: the function to be wrapped with constraints
    :type f: callable
    :param box: the box, as a dict: ``{'param_name': [lb, ub], ...}``
    :type box: dict
    :param default: function value to default to when constraints
        are violated
    :type default: number

    """
    return wrap_constraints(f, default, range_oo=box)


def maximize_structured(f, search_space, num_evals=50, pmap=map, save_dir=None, restore_file_path=None):
    """Basic function maximization routine. Maximizes ``f`` within
    the given box constraints.

    :param f: the function to be maximized
    :param search_space: the search space (see :doc:`/user/structured_search_spaces` for details)
    :param num_evals: number of permitted function evaluations
    :param pmap: the map function to use
    :type pmap: callable
    :returns: retrieved maximum, extra information and solver info

    This function will implicitly choose an appropriate solver and
    its initialization based on ``num_evals`` and the box constraints.

    """
    tree = search_spaces.SearchTree(search_space)
    box = tree.to_box()

    # we need to position the call log here
    # because the function signature used later on is internal logic
    f = fun.logged(f)

    # wrap the decoder and constraints for the internal search space representation
    f = tree.wrap_decoder(f)
    f = _wrap_hard_box_constraints(f, box, -sys.float_info.max)

    suggestion = suggest_solver(num_evals, "particle swarm", **box)
    solver = make_solver(**suggestion)
    solution, details = optimize(solver, f, maximize=True, max_evals=num_evals,
                                 pmap=pmap, decoder=tree.decode, save_dir=save_dir, restore_file_path=restore_file_path)
    return solution, details, suggestion


def minimize_structured(f, search_space, num_evals=50, pmap=map, save_dir=None, restore_file_path=None):
    """Basic function minimization routine. Minimizes ``f`` within
    the given box constraints.

    :param f: the function to be maximized
    :param search_space: the search space (see :doc:`/user/structured_search_spaces` for details)
    :param num_evals: number of permitted function evaluations
    :param pmap: the map function to use
    :type pmap: callable
    :returns: retrieved maximum, extra information and solver info

    This function will implicitly choose an appropriate solver and
    its initialization based on ``num_evals`` and the box constraints.

    """
    tree = search_spaces.SearchTree(search_space)
    box = tree.to_box()

    # we need to position the call log here
    # because the function signature used later on is internal logic
    f = fun.logged(f)

    # wrap the decoder and constraints for the internal search space representation
    f = tree.wrap_decoder(f)
    f = _wrap_hard_box_constraints(f, box, sys.float_info.max)

    suggestion = suggest_solver(num_evals, "particle swarm", **box)
    solver = make_solver(**suggestion)
    solution, details = optimize(solver, f, maximize=False, max_evals=num_evals,
                                 pmap=pmap, decoder=tree.decode, save_dir=save_dir, restore_file_path=restore_file_path)
    return solution, details, suggestion
