# (c) Alexander Solovyov, 2009-2011, under terms of the new BSD License
'''Command line arguments parser
'''

import sys, traceback, getopt, types, textwrap, inspect, os, copy, keyword
from itertools import imap
from functools import wraps


__all__ = ['Dispatcher', 'command', 'dispatch']
__version__ = '3.3.1'
__author__ = 'Alexander Solovyov'
__email__ = 'alexander@solovyov.net'


try:
    import locale
    ENCODING = locale.getpreferredencoding()
    if (not ENCODING or ENCODING == 'mac-roman' or 'ascii' in ENCODING.lower()
        or 'ansi' in ENCODING.lower()):
        ENCODING = 'UTF-8'
except locale.Error:
    ENCODING = 'UTF-8'


def write(text, out=None):
    '''Write output to a given stream (stdout by default)'''
    out = out or sys.stdout
    if sys.version_info < (3, 0) and isinstance(text, unicode):
        text = text.encode(ENCODING)
    out.write(text)


def err(text):
    '''Write output to stderr'''
    write(text, out=sys.stderr)


class Dispatcher(object):
    '''Central object for command dispatching system

    - ``cmdtable``: dict of commands. Will be populated with functions,
      decorated with ``Dispatcher.command``.
    - ``globaloptions``: list of options which are applied to all
      commands, will contain ``--help`` option at least.
    - ``middleware``: global decorator for all commands.
    '''

    def __init__(self, cmdtable=None, globaloptions=None, middleware=None):
        self._cmdtable = cmdtable or {}
        self._globaloptions = globaloptions or []
        self.middleware = middleware

    @property
    def globaloptions(self):
        opts = self._globaloptions[:]
        if not next((True for o in opts if o[1] == 'help'), None):
            opts.append(('h', 'help', False, 'display help'))
        return opts

    @property
    def cmdtable(self):
        table = self._cmdtable.copy()
        table['help'] = help_(table, self.globaloptions), [], '[TOPIC]'
        return table

    def command(self, options=None, usage=None, name=None, shortlist=False,
                hide=False, aliases=()):
        '''Decorator to mark function to be used as command for CLI.

        Usage::

          from opster import command, dispatch

          @command()
          def run(argument,
                  optionalargument=None,
                  option=('o', 'default', 'help for option'),
                  no_short_name=('', False, 'help for this option')):
              print argument, optionalargument, option, no_short_name

          if __name__ == '__main__':
              run.command()

          # or, if you want to have multiple subcommands:
          if __name__ == '__main__':
              dispatch()

        Optional arguments:
         - ``options``: options in format described later. If not supplied,
           will be determined from function.
         - ``usage``: usage string for function, replaces ``%name`` with name
           of program or subcommand. In case if it's subcommand and ``%name``
           is not present, usage is prepended by ``name``
         - ``name``: used for multiple subcommands. Defaults to wrapped
           function name
         - ``shortlist``: if command should be included in shortlist. Used
           only with multiple subcommands
         - ``hide``: if command should be hidden from help listing. Used only
           with multiple subcommands, overrides ``shortlist``
         - ``aliases``: list of aliases for command

        If defined, options should be a list of 4-tuples in format::

          (shortname, longname, default, help)

        Where:

         - ``shortname`` is a single letter which can be used then as an option
           specifier on command line (like ``-a``). Will be not used if contains
           falsy value (empty string, for example)
         - ``longname`` - main identificator of an option, can be used as on a
           command line with double dashes (like ``--longname``)
         - ``default`` value for an option, type of it determines how option
           will be processed
         - ``help`` string displayed as a help for an option when asked to
        '''
        def wrapper(func):
            try:
                options_ = list(options or guess_options(func))
            except TypeError:
                options_ = []

            cmdname = name or name_from_python(func.__name__)
            scriptname = name or sysname()
            if usage is None:
                usage_ = guess_usage(func, options_)
            else:
                usage_ = usage
            prefix = hide and '~' or (shortlist and '^' or '')
            cmdname = prefix + cmdname
            if aliases:
                cmdname = cmdname + '|' + '|'.join(aliases)
            self._cmdtable[cmdname] = (func, options_, usage_)

            def help_func(name=None):
                return help_cmd(func, replace_name(usage_, sysname()), options_,
                                aliases)

            def command(argv=None):
                for o in self.globaloptions:
                    if not next((x for x in options_ if
                                 x[1] == o[1] or (x[0] and x[0] == o[0])),
                                None):
                        options_.append(o)

                if argv is None:
                    argv = sys.argv[1:]
                try:
                    args, opts = process(argv, options_)
                except Exception, e:
                    if exchandle(e, func.help):
                        return -1
                    raise

                if opts.pop('help', False):
                    return func.help()

                try:
                    return call_cmd(scriptname, func, options_)(*args, **opts)
                except Exception, e:
                    if exchandle(e, func.help):
                        return -1
                    raise

            func.usage = usage_
            func.help = help_func
            func.command = command
            func.opts = options_
            func.orig = func

            @wraps(func)
            def inner(*args, **opts):
                return call_cmd_regular(func, options_)(*args, **opts)

            return inner

        return wrapper

    def _dispatch(self, args):
        cmd, func, args, options = cmdparse(args, self.cmdtable,
                                            self.globaloptions)
        try:
            args, kwargs = process(args, options)
        except getopt.GetoptError, e:
            # FIXME: this is ugly, we set command name here to retrieve it later
            # in exchandle().
            e.command = cmd
            raise

        if kwargs.pop('help', False):
            return 'help', self.cmdtable['help'][0], [cmd], {}, options
        if not cmd:
            return 'help', self.cmdtable['help'][0], ['shortlist'], {}, options

        return cmd, func, args, kwargs, options

    def dispatch(self, args=None):
        '''Dispatch command line arguments using subcommands

        - ``args``: list of arguments, default: ``sys.argv[1:]``
        '''
        args = args or sys.argv[1:]

        help_func = self.cmdtable['help'][0]
        autocomplete(self.cmdtable, args, self.middleware)

        try:
            name, func, args, kwargs, options = self._dispatch(args)
        except Exception, e:
            if exchandle(e, help_func):
                return -1
            raise

        try:
            mw = name != '_completion' and self.middleware or None
            return call_cmd(name, func, options, mw)(*args, **kwargs)
        except Exception, e:
            if exchandle(e, help_func):
                return -1
            raise


_dispatcher = None


def command(options=None, usage=None, name=None, shortlist=False, hide=False,
            aliases=()):
    global _dispatcher
    if not _dispatcher:
        _dispatcher = Dispatcher()
    return _dispatcher.command(options=options, usage=usage, name=name,
                               shortlist=shortlist, hide=hide, aliases=aliases)
command.__doc__ = Dispatcher.command.__doc__


def dispatch(args=None, cmdtable=None, globaloptions=None, middleware=None):
    global _dispatcher
    if not _dispatcher:
        _dispatcher = Dispatcher(cmdtable, globaloptions, middleware)
    else:
        if cmdtable:
            _dispatcher._cmdtable = cmdtable
        if globaloptions:
            _dispatcher._globaloptions = globaloptions
        if middleware:
            _dispatcher.middleware = middleware
    return _dispatcher.dispatch(args)
dispatch.__doc__ = Dispatcher.dispatch.__doc__


# --------
# Help
# --------

def help_(cmdtable, globalopts):
    '''Help generator for a command table
    '''
    def help_inner(name=None, **opts):
        '''Show help for a given help topic or a help overview

        With no arguments, print a list of commands with short help messages.

        Given a command name, print help for that command.
        '''
        def helplist():
            hlp = {}
            # determine if any command is marked for shortlist
            shortlist = (name == 'shortlist' and
                         any(imap(lambda x: x.startswith('^'), cmdtable)))

            for cmd, info in cmdtable.items():
                if cmd.startswith('~'):
                    continue  # do not display hidden commands
                if shortlist and not cmd.startswith('^'):
                    continue  # short help contains only marked commands
                cmd = cmd.lstrip('^~')
                doc = pretty_doc_string(info[0])
                hlp[cmd] = doc.strip().splitlines()[0].rstrip()

            hlplist = sorted(hlp)
            maxlen = max(map(len, hlplist))

            write('usage: %s <command> [options]\n' % sysname())
            write('\ncommands:\n\n')
            for cmd in hlplist:
                doc = hlp[cmd]
                write(' %-*s  %s\n' % (maxlen, cmd.split('|', 1)[0], doc))

        if not cmdtable:
            return err('No commands specified!\n')

        if not name or name == 'shortlist':
            return helplist()

        aliases, (cmd, options, usage) = findcmd(name, cmdtable)
        return help_cmd(cmd,
                        replace_name(usage, sysname() + ' ' + aliases[0]),
                        options + globalopts,
                        aliases[1:])
    return help_inner


def help_cmd(func, usage, options, aliases):
    '''show help for given command

    - ``func``: function to generate help for (``func.__doc__`` is taken)
    - ``usage``: usage string
    - ``options``: options in usual format

    >>> def test(*args, **opts):
    ...     """that's a test command
    ...
    ...        you can do nothing with this command"""
    ...     pass
    >>> opts = [('l', 'listen', 'localhost',
    ...          'ip to listen on'),
    ...         ('p', 'port', 8000,
    ...          'port to listen on'),
    ...         ('d', 'daemonize', False,
    ...          'daemonize process'),
    ...         ('', 'pid-file', '',
    ...          'name of file to write process ID to')]
    >>> help_cmd(test, 'test [-l HOST] [NAME]', opts, ())
    test [-l HOST] [NAME]
    <BLANKLINE>
    that's a test command
    <BLANKLINE>
           you can do nothing with this command
    <BLANKLINE>
    options:
    <BLANKLINE>
     -l --listen     ip to listen on (default: localhost)
     -p --port       port to listen on (default: 8000)
     -d --daemonize  daemonize process
        --pid-file   name of file to write process ID to
    '''
    write(usage + '\n')
    if aliases:
        write('\naliases: ' + ', '.join(aliases) + '\n')
    doc = pretty_doc_string(func)
    write('\n' + doc.strip() + '\n\n')
    if options:
        write(''.join(help_options(options)))


def help_options(options):
    '''Generator for help on options
    '''
    yield 'options:\n\n'
    output = []
    for o in options:
        short, name, default, desc = o[:4]
        if hasattr(default, '__call__'):
            default = default(None)
        default = default and ' (default: %s)' % default or ''
        output.append(('%2s%s' % (short and '-%s' % short,
                                  name and ' --%s' % name),
                       '%s%s' % (desc, default)))

    opts_len = max([len(first) for first, second in output if second] or [0])
    for first, second in output:
        if second:
            # wrap description at 78 chars
            second = textwrap.wrap(second, width=(78 - opts_len - 3))
            pad = '\n' + ' ' * (opts_len + 3)
            yield ' %-*s  %s\n' % (opts_len, first, pad.join(second))
        else:
            yield '%s\n' % first


# --------
# Options process
# --------

def process(args, options, preparse=False):
    '''
    >>> opts = [('l', 'listen', 'localhost',
    ...          'ip to listen on'),
    ...         ('p', 'port', 8000,
    ...          'port to listen on'),
    ...         ('d', 'daemonize', False,
    ...          'daemonize process'),
    ...         ('', 'pid-file', '',
    ...          'name of file to write process ID to')]
    >>> print process(['-l', '0.0.0.0', '--pi', 'test', 'all'], opts)
    (['all'], {'pid_file': 'test', 'daemonize': False, 'port': 8000, 'listen': '0.0.0.0'})

    '''
    argmap, defmap, state = {}, {}, {}
    shortlist, namelist, funlist = '', [], []

    for o in options:
        # might have the fifth completer element
        short, name, default, comment = o[:4]
        if short and len(short) != 1:
            raise OpsterError(
                'Short option should be only a single character: %s' % short)
        if not name:
            raise OpsterError(
                'Long name should be defined for every option')
        # change name to match Python styling
        pyname = name_to_python(name)
        argmap['-' + short] = argmap['--' + name] = pyname
        defmap[pyname] = default

        # copy defaults to state
        if isinstance(default, (list, dict)):
            state[pyname] = copy.copy(default)
        elif isinstance(default, types.FunctionType):
            funlist.append(pyname)
            state[pyname] = None
        else:
            state[pyname] = default

        # getopt wants indication that it takes a parameter
        if not (default is None or default is True or default is False):
            if short:
                short += ':'
            if name:
                name += '='
        if short:
            shortlist += short
        if name:
            namelist.append(name)

    try:
        opts, args = getopt.gnu_getopt(args, shortlist, namelist)
    except getopt.GetoptError, e:
        if preparse:
            prefix = '-' if len(e.opt) == 1 else '--'
            args = args[:]
            args.insert(args.index(prefix + e.opt), '--')
            opts, args = getopt.gnu_getopt(args, shortlist, namelist)
            return args, None
        raise

    # transfer result to state
    for opt, val in opts:
        name = argmap[opt]
        t = type(defmap[name])
        if t is types.FunctionType:
            del funlist[funlist.index(name)]
            state[name] = defmap[name](val)
        elif t is list:
            state[name].append(val)
        elif t is dict:
            try:
                k, v = val.split('=')
            except ValueError:
                raise getopt.GetoptError(
                    "wrong definition: %r (should be in format KEY=VALUE)"
                    % val)
            state[name][k] = v
        elif t in (types.NoneType, types.BooleanType):
            state[name] = not defmap[name]
        elif t in (int, float):
            try:
                state[name] = t(val)
            except ValueError:
                raise getopt.GetoptError(
                    'invalid option value %r for option %r'
                    % (val, name))
        else:
            state[name] = t(val)

    for name in funlist:
        state[name] = defmap[name](None)

    return args, state


# --------
# Subcommand system
# --------

def cmdparse(args, cmdtable, globalopts):
    '''Parse arguments list to find a command, options and arguments
    '''
    # pre-parse arguments here using global options to find command name,
    # which is first non-option entry
    cmd = next((arg for arg in process(args, globalopts, preparse=True)[0]
                if not arg.startswith('-')), None)

    if cmd:
        args.pop(args.index(cmd))

        aliases, info = findcmd(cmd, cmdtable)
        cmd = aliases[0]
        possibleopts = list(info[1])
    else:
        possibleopts = []

    possibleopts.extend(globalopts)
    return cmd, cmd and info[0] or None, args, possibleopts


def aliases_(cmdtable_key):
    '''Get aliases from a command table key'''
    return cmdtable_key.lstrip("^~").split("|")


def findpossible(cmd, table):
    """
    Return cmd -> (aliases, command table entry)
    for each matching command.
    """
    choice = {}
    for e in table.keys():
        aliases = aliases_(e)
        found = None
        if cmd in aliases:
            found = cmd
        else:
            for a in aliases:
                if a.startswith(cmd):
                    found = a
                    break
        if found is not None:
            choice[found] = (aliases, table[e])

    return choice


def findcmd(cmd, table):
    """Return (aliases, command table entry) for command string."""
    choice = findpossible(cmd, table)

    if cmd in choice:
        return choice[cmd]

    if len(choice) > 1:
        clist = choice.keys()
        clist.sort()
        raise AmbiguousCommand(cmd, clist)

    if choice:
        return choice.values()[0]

    raise UnknownCommand(cmd)


# --------
# Helpers
# --------

def guess_options(func):
    '''Get options definitions from function

    They should be declared in a following way:

    def func(longname=(shortname, default, help)):
        pass

    See docstring of ``command()`` for description of those variables.
    '''
    args, _, _, defaults = inspect.getargspec(func)
    for name, option in zip(args[-len(defaults):], defaults):
        if not isinstance(option, tuple):
            continue
        sname, default, hlp = option[:3]
        completer = option[3] if len(option) > 3 else None
        yield (sname, name_from_python(name), default, hlp, completer)


def guess_usage(func, options):
    '''Get usage definition for a function
    '''
    usage = ['%name']
    if options:
        usage.append('[OPTIONS]')
    arginfo = inspect.getargspec(func)
    optnames = [x[1] for x in options]
    nonoptional = len(arginfo.args) - len(arginfo.defaults or ())

    for i, arg in enumerate(arginfo.args):
        if arg not in optnames:
            usage.append((i > nonoptional - 1 and '[%s]' or '%s')
                         % arg.upper())

    if arginfo.varargs:
        usage.append('[%s ...]' % arginfo.varargs.upper())
    return ' '.join(usage)


def exchandle(e, help_func):
    '''Handle internal exceptions and print human-readable information on them

    Returns False is exception is not suitable
    '''
    if isinstance(e, UnknownCommand):
        err("unknown command: '%s'\n" % e)
    elif isinstance(e, AmbiguousCommand):
        err("command '%s' is ambiguous:\n    %s\n" %
            (e.args[0], ' '.join(e.args[1])))
    elif isinstance(e, ParseError):
        err('%s: %s\n\n' % (e.args[0], e.args[1].strip()))
        help_func(e.args[0])
    elif isinstance(e, getopt.GetoptError):
        err('error: %s\n\n' % e)
        # we may get command name here, if we're in multicommand context
        help_func(getattr(e, 'command', None))
    elif isinstance(e, OpsterError):
        err('%s\n' % e)
    else:
        return False
    return True


def call_cmd(name, func, opts, middleware=None):
    '''Wrapper for command call, catching situation with insufficient arguments
    '''
    # depth is necessary when there is a middleware in setup
    arginfo = inspect.getargspec(func)
    if middleware:
        tocall = middleware(func)
        depth = 2
    else:
        tocall = func
        depth = 1

    def inner(*args, **kwargs):
        # NOTE: this is not very nice, but it fixes problem with
        # TypeError: func() got multiple values for 'argument'
        # Would be nice to find better way
        prepend = []
        start = None
        if arginfo.varargs and len(args) > (len(arginfo.args) - len(kwargs)):
            for o in opts:
                optname = o[1].replace('-', '_')
                if optname in arginfo.args:
                    if start is None:
                        start = arginfo.args.index(optname)
                    prepend.append(optname)
            if start is not None:  # do we have to prepend anything
                args = (args[:start] +
                        tuple(kwargs.pop(x) for x in prepend) +
                        args[start:])

        try:
            return tocall(*args, **kwargs)
        except TypeError:
            if len(traceback.extract_tb(sys.exc_info()[2])) == depth:
                raise ParseError(name, "invalid arguments")
            raise
    return inner


def call_cmd_regular(func, opts):
    '''Wrapper for command for handling function calls from Python
    '''
    def inner(*args, **kwargs):
        arginfo = inspect.getargspec(func)
        if len(args) > len(arginfo.args):
            raise TypeError('You have supplied more positional arguments'
                            ' than applicable')

        # short name, long name, default, help, (maybe) completer
        funckwargs = dict((o[1].replace('-', '_'), o[2])
                          for o in opts)
        if 'help' not in (arginfo.defaults or ()) and not arginfo.keywords:
            funckwargs.pop('help', None)
        funckwargs.update(kwargs)
        return func(*args, **funckwargs)
    return inner


def replace_name(usage, name):
    '''Replace name placeholder with a command name'''
    if '%name' in usage:
        return usage.replace('%name', name, 1)
    return name + ' ' + usage


def sysname():
    '''Returns name of executing file'''
    name = sys.argv[0]
    if name.startswith('/'):
        return name.rsplit('/', 1)[1]
    elif name.startswith('./'):
        return name[2:]
    return name


def pretty_doc_string(item):
    "Doc string with adjusted indentation level of the 2nd line and beyond."
    raw_doc = item.__doc__ or '(no help text available)'
    lines = raw_doc.strip().splitlines()
    if len(lines) <= 1:
        return raw_doc
    indent = len(lines[1]) - len(lines[1].lstrip())
    return '\n'.join([lines[0]] + map(lambda l: l[indent:], lines[1:]))


def name_from_python(name):
    if name.endswith('_') and keyword.iskeyword(name[:-1]):
        name = name[:-1]
    return name.replace('_', '-')


def name_to_python(name):
    name = name.replace('-', '_')
    if keyword.iskeyword(name):
        return name + '_'
    return name


# --------
# Autocomplete system
# --------

# Borrowed from PIP
def autocomplete(cmdtable, args, middleware):
    """Command and option completion.

    Enable by sourcing one of the completion shell scripts (bash or zsh).
    """

    # Don't complete if user hasn't sourced bash_completion file.
    if 'OPSTER_AUTO_COMPLETE' not in os.environ:
        return
    cwords = os.environ['COMP_WORDS'].split()[1:]
    cword = int(os.environ['COMP_CWORD'])

    try:
        current = cwords[cword - 1]
    except IndexError:
        current = ''

    commands = []
    for k in cmdtable.keys():
        commands += aliases_(k)

    # command
    if cword == 1:
        print ' '.join(filter(lambda x: x.startswith(current), commands))

    # command options
    elif cwords[0] in commands:
        idx = -2 if current else -1
        options = []
        aliases, (cmd, opts, usage) = findcmd(cwords[0], cmdtable)

        for o in opts:
            short, long, default, help = o[:4]
            completer = o[4] if len(o) > 4 else None
            short, long = '-%s' % short, '--%s' % long
            options += [short, long]

            if cwords[idx] in (short, long) and completer:
                if middleware:
                    completer = middleware(completer)
                args = completer(current)
                print ' '.join(args),

        print ' '.join((o for o in options if o.startswith(current)))

    sys.exit(1)


COMPLETIONS = {
    'bash':
        """
# opster bash completion start
_opster_completion()
{
    COMPREPLY=( $( COMP_WORDS="${COMP_WORDS[*]}" \\
                   COMP_CWORD=$COMP_CWORD \\
                   OPSTER_AUTO_COMPLETE=1 $1 ) )
}
complete -o default -F _opster_completion %s
# opster bash completion end
""",
    'zsh':
            """
# opster zsh completion start
function _opster_completion {
  local words cword
  read -Ac words
  read -cn cword
  reply=( $( COMP_WORDS="$words[*]" \\
             COMP_CWORD=$(( cword-1 )) \\
             OPSTER_AUTO_COMPLETE=1 $words[1] ) )
}
compctl -K _opster_completion %s
# opster zsh completion end
"""
    }


@command(name='_completion', hide=True)
def completion(type=('t', 'bash', 'Completion type (bash or zsh)'),
               # kwargs will catch every global option, which we get
               # anyway, because middleware is skipped
               **kwargs):
    """Outputs completion script for bash or zsh."""

    prog_name = os.path.split(sys.argv[0])[1]
    print COMPLETIONS[type].strip() % prog_name


# --------
# Exceptions
# --------

class OpsterError(Exception):
    'Base opster exception'


class AmbiguousCommand(OpsterError):
    'Raised if command is ambiguous'


class UnknownCommand(OpsterError):
    'Raised if command is unknown'


class ParseError(OpsterError):
    'Raised on error in command line parsing'


if __name__ == '__main__':
    import doctest
    doctest.testmod()
