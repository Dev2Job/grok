import os
import inspect

import zope.component.interface
from zope import interface, component
from zope.publisher.interfaces.browser import (IDefaultBrowserLayer,
                                               IBrowserRequest,
                                               IBrowserPublisher)
from zope.publisher.interfaces.xmlrpc import IXMLRPCRequest
from zope.security.checker import NamesChecker, defineChecker
from zope.security.permission import Permission

from zope.app.publisher.xmlrpc import MethodPublisher
from zope.app.container.interfaces import INameChooser

import grok
from grok import util, components, formlib
from grok.error import GrokError

class ModelGrokker(grok.ClassGrokker):
    component_class = grok.Model

    def register(self, context, name, factory, module_info, templates):
        for field in formlib.get_context_schema_fields(factory):
            setattr(factory, field.__name__, field.default)       

class ContainerGrokker(ModelGrokker):
    component_class = grok.Container
    
class LocalUtilityGrokker(ModelGrokker):
    component_class = grok.LocalUtility
    
class AdapterGrokker(grok.ClassGrokker):
    component_class = grok.Adapter

    def register(self, context, name, factory, module_info, templates):
        adapter_context = util.determine_class_context(factory, context)
        provides = util.class_annotation(factory, 'grok.provides', None)
        if provides is None:
            util.check_implements_one(factory)
        name = util.class_annotation(factory, 'grok.name', '')
        component.provideAdapter(factory, adapts=(adapter_context,),
                                 provides=provides,
                                 name=name)
            
class MultiAdapterGrokker(grok.ClassGrokker):
    component_class = grok.MultiAdapter
    
    def register(self, context, name, factory, module_info, templates):
        provides = util.class_annotation(factory, 'grok.provides', None)
        if provides is None:
            util.check_implements_one(factory)
        util.check_adapts(factory)
        name = util.class_annotation(factory, 'grok.name', '')
        component.provideAdapter(factory, provides=provides, name=name)

class GlobalUtilityGrokker(grok.ClassGrokker):
    component_class = grok.GlobalUtility

    def register(self, context, name, factory, module_info, templates):
        provides = util.class_annotation(factory, 'grok.provides', None)
        if provides is None:
            util.check_implements_one(factory)
        name = util.class_annotation(factory, 'grok.name', '')
        component.provideUtility(factory(), provides=provides, name=name)

class XMLRPCGrokker(grok.ClassGrokker):
    component_class = grok.XMLRPC

    def register(self, context, name, factory, module_info, templates):
        view_context = util.determine_class_context(factory, context)
        candidates = [getattr(factory, name) for name in dir(factory)]
        methods = [c for c in candidates if inspect.ismethod(c)]

        for method in methods:
            # Make sure that the class inherits MethodPublisher, so that the
            # views have a location
            method_view = type(
                factory.__name__, (factory, MethodPublisher),
                {'__call__': method}
                )
            component.provideAdapter(
                method_view, (view_context, IXMLRPCRequest),
                interface.Interface,
                name=method.__name__)

            checker = NamesChecker(['__call__'])
            defineChecker(method_view, checker)

class ViewGrokker(grok.ClassGrokker):
    component_class = grok.View

    def register(self, context, name, factory, module_info, templates):
        view_context = util.determine_class_context(factory, context)

        factory.module_info = module_info

        # some extra work to take care of if this view is a form
        if util.check_subclass(factory, components.EditForm):
            formlib.setup_editform(factory, view_context)
        elif util.check_subclass(factory, components.DisplayForm):
            formlib.setup_displayform(factory, view_context)
        elif util.check_subclass(factory, components.AddForm):
            formlib.setup_addform(factory, view_context)

        factory_name = factory.__name__.lower()

        # find templates
        template_name = util.class_annotation(factory, 'grok.template',
                                              factory_name)
        template = templates.get(template_name)

        if factory_name != template_name:
            # grok.template is being used
            if templates.get(factory_name):
                raise GrokError("Multiple possible templates for view %r. It "
                                "uses grok.template('%s'), but there is also "
                                "a template called '%s'."
                                % (factory, template_name, factory_name),
                                factory)

        # we never accept a 'render' method for forms
        if util.check_subclass(factory, components.Form):
            if getattr(factory, 'render', None):
                raise GrokError(
                    "It is not allowed to specify a custom 'render' "
                    "method for form %r. Forms either use the default "
                    "template or a custom-supplied one." % factory,
                    factory)

        if template:
            if getattr(factory, 'render', None):
                # we do not accept render and template both for a view
                raise GrokError(
                    "Multiple possible ways to render view %r. "
                    "It has both a 'render' method as well as "
                    "an associated template." % factory,
                    factory)

            templates.markAssociated(template_name)
            factory.template = template
        else:
            if not getattr(factory, 'render', None):
                if util.check_subclass(factory, components.EditForm):
                    # we have a edit form without template
                    factory.template = formlib.defaultEditTemplate
                elif util.check_subclass(factory, components.DisplayForm):
                    # we have a display form without template
                    factory.template = formlib.defaultDisplayTemplate
                elif util.check_subclass(factory, components.AddForm):
                    # we have an add form without template
                    factory.template = formlib.defaultEditTemplate
                else:
                    # we do not accept a view without any way to render it
                    raise GrokError("View %r has no associated template or "
                                    "'render' method." % factory,
                                    factory)

        view_name = util.class_annotation(factory, 'grok.name',
                                          factory_name)
        # __view_name__ is needed to support IAbsoluteURL on views
        factory.__view_name__ = view_name
        component.provideAdapter(factory,
                                 adapts=(view_context, IDefaultBrowserLayer),
                                 provides=interface.Interface,
                                 name=view_name)

        # protect view, public by default
        permission = util.class_annotation(factory, 'grok.require', None)
        if permission is None:
            checker = NamesChecker(['__call__'])
        else:
            checker = NamesChecker(['__call__'], permission)
        defineChecker(factory, checker)

class TraverserGrokker(grok.ClassGrokker):
    component_class = grok.Traverser

    def register(self, context, name, factory, module_info, templates):
        factory_context = util.determine_class_context(factory, context)
        component.provideAdapter(factory,
                                 adapts=(factory_context, IBrowserRequest),
                                 provides=IBrowserPublisher)
    
class ModulePageTemplateGrokker(grok.InstanceGrokker):
    # this needs to happen before any other grokkers execute that actually
    # use the templates
    priority = 1000

    component_class = grok.PageTemplate

    def register(self, context, name, instance, module_info, templates):
        templates.register(name, instance)
        instance._annotateGrokInfo(name, module_info.dotted_name)

class FilesystemPageTemplateGrokker(grok.ModuleGrokker):
    # do this early on, but after ModulePageTemplateGrokker, as
    # findFilesystem depends on module-level templates to be
    # already grokked for error reporting
    priority = 999
    
    def register(self, context, module_info, templates):
        templates.findFilesystem(module_info)

class SubscriberGrokker(grok.ModuleGrokker):

    def register(self, context, module_info, templates):
        subscribers = module_info.getAnnotation('grok.subscribers', [])
    
        for factory, subscribed in subscribers:
            component.provideHandler(factory, adapts=subscribed)
            for iface in subscribed:
                zope.component.interface.provideInterface('', iface)

class StaticResourcesGrokker(grok.ModuleGrokker):

    def register(self, context, module_info, templates):
        # we're only interested in static resources if this module
        # happens to be a package
        if not module_info.isPackage():
            return
        
        resource_path = module_info.getResourcePath('static')
        if os.path.isdir(resource_path):
            static_module = module_info.getSubModuleInfo('static')
            if static_module is not None:
                if static_module.isPackage():
                    raise GrokError(
                        "The 'static' resource directory must not "
                        "be a python package.",
                        module_info.getModule())
                else:
                    raise GrokError(
                        "A package can not contain both a 'static' "
                        "resource directory and a module named "
                        "'static.py'", module_info.getModule())
        
        resource_factory = components.DirectoryResourceFactory(
            resource_path, module_info.dotted_name)
        component.provideAdapter(
            resource_factory, (IDefaultBrowserLayer,),
            interface.Interface, name=module_info.dotted_name)

class GlobalUtilityDirectiveGrokker(grok.ModuleGrokker):

    def register(self, context, module_info, templates):
        infos = module_info.getAnnotation('grok.global_utility', [])
    
        for info in infos:
            component.provideUtility(info.factory(),
                                     provides=info.provides,
                                     name=info.name)
class SiteGrokker(grok.ClassGrokker):
    component_class = grok.Site
    priority = 500
    continue_scanning = True

    def register(self, context, name, factory, module_info, templates):
        infos = util.class_annotation(factory, 'grok.local_utility', None)
        if infos is None:
            return
        subscriber = LocalUtilityRegistrationSubscriber(infos)
        component.provideHandler(subscriber,
                                 adapts=(factory, grok.IObjectAddedEvent))

class LocalUtilityRegistrationSubscriber(object):
    def __init__(self, infos):
        self.infos = infos

    def __call__(self, site, event):
        for info in self.infos:
            utility = info.factory()
            site_manager = site.getSiteManager()
            
            # store utility
            if info.hide:
                container = site_manager['default']
            else:
                container = site
                
            name_in_container = info.name_in_container 
            if name_in_container is None:
                name_in_container = INameChooser(container).chooseName(
                    info.factory.__class__.__name__,
                    utility)
            container[name_in_container] = utility

            # execute setup callback
            if info.setup is not None:
                info.setup(utility)

            # register utility
            site_manager.registerUtility(utility, provided=info.provides,
                                         name=info.name)

class DefinePermissionGrokker(grok.ModuleGrokker):

    def register(self, context, module_info, templates):
        permissions = module_info.getAnnotation('grok.define_permission', [])
        for permission in permissions:
            # TODO permission title and description
            component.provideUtility(Permission(permission), name=permission)
